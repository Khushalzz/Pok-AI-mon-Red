import socket
import json
import charmap
import os
import threading
import time

from transformers import pipeline

# Load the tiny LLM
print("Loading Qwen 1.5B (this will take a moment to download if it's your first time)...", flush=True)

# Check if the user has downloaded their trained adapter from Kaggle
adapter_path = "./pokemon_adapter"
if os.path.exists(adapter_path):
    print(f"Found Custom LoRA Adapter at {adapter_path}! Loading Fine-Tuned Model...", flush=True)
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    base_model = AutoModelForCausalLM.from_pretrained("yasserrmd/Human-Like-Qwen2.5-1.5B-Instruct", device_map="cpu")
    model = PeftModel.from_pretrained(base_model, adapter_path)
    tokenizer = AutoTokenizer.from_pretrained("yasserrmd/Human-Like-Qwen2.5-1.5B-Instruct")
    generator = pipeline("text-generation", model=model, tokenizer=tokenizer, device="cpu")
else:
    print("Loading Base Model (No custom adapter found)...", flush=True)
    generator = pipeline("text-generation", model="yasserrmd/Human-Like-Qwen2.5-1.5B-Instruct", device="cpu")

print("Model loaded successfully!", flush=True)

# Set up the TCP Socket Server
HOST = "127.0.0.1"
PORT = 8000

server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_sock.bind((HOST, PORT))
server_sock.listen(1)

print("Loading text database...", flush=True)
try:
    with open("text_database.json", "r", encoding="utf-8") as f:
        text_database = json.load(f)
    print(f"Loaded {len(text_database)} dialog strings!", flush=True)
except Exception as e:
    print(f"Could not load database: {e}", flush=True)
    text_database = []

# --- State & Locks ---
# state_lock protects pregen_queues and interacted_npcs from threading race conditions
state_lock = threading.Lock()
generator_lock = threading.Lock()

pregen_queues = {}       # npc_key -> list of pre-generated jokes
proximity_index = 0
interacted_npcs = {}    # npc_key -> timestamp of first interaction in current visit
CONVERSATION_COOLDOWN = 10  # seconds before same text is a NEW visit


# --- Helpers ---

def _truncate_to_word_boundary(text, max_len=150):
    """Truncate text to max_len chars, stopping at a word boundary."""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    idx = truncated.rfind(" ")
    if idx > 0:
        return truncated[:idx]
    return truncated  # no spaces found, return as-is


def _clean_llm_output(raw):
    """Strip LLM special tokens and normalize whitespace."""
    text = raw.strip()
    text = text.replace("<|im_end|>", "").replace("<|endoftext|>", "")
    text = " ".join(text.split())
    return text


def paginate_text(text, max_chars=18):
    """Break text into Gen 1 two-line pages with PARA separators."""
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        # Split words longer than max_chars to avoid textbox overflow
        while len(word) > max_chars:
            lines.append(word[:max_chars])
            word = word[max_chars:]

        if len(current_line) + len(word) + (1 if current_line else 0) <= max_chars:
            current_line = (current_line + " " + word).strip() if current_line else word
        else:
            lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    paginated = ""
    for i, line in enumerate(lines):
        paginated += line
        if i == len(lines) - 1:
            break
        if i % 2 == 0:
            paginated += "\n"    # Next Line (0x4F)
        else:
            paginated += "\x01"  # Paragraph (0x51) — clears box, waits for A press

    return paginated


# --- Background Generation ---

def generate_joke_for(npc_text):
    """Background thread: generates a joke and caches it for the given NPC text."""
    prompt = f"Original NPC text: '{npc_text}'\nRewrite this as a short, funny joke.\nJoke:"
    messages = [{"role": "user", "content": prompt}]

    with generator_lock:
        try:
            result = generator(messages, max_new_tokens=25, temperature=0.8, do_sample=True)
            raw = result[0]['generated_text'][-1]['content']
            new_text = _clean_llm_output(raw)
            new_text = _truncate_to_word_boundary(new_text)

            if not new_text:
                print("[Background] LLM returned empty output. Skipping cache.", flush=True)
                return

            with state_lock:
                if npc_text not in pregen_queues:
                    pregen_queues[npc_text] = []
                pregen_queues[npc_text].append(new_text)

            print("[Background] Joke cached! Ready for next interaction.", flush=True)
        except Exception as e:
            print(f"[Background] Generation failed: {e}", flush=True)


def background_restocker():
    """Pre-generates jokes for the dialogue strings near the player's current position."""
    global proximity_index
    print("\n[Background] Dynamic Proximity Pre-Fetcher Started!", flush=True)

    while True:
        if not text_database:
            time.sleep(1)
            continue

        all_filled = True

        start_idx = max(0, proximity_index - 2)
        end_idx = min(len(text_database), proximity_index + 20)

        for i in range(start_idx, end_idx):
            context_str = text_database[i]

            with state_lock:
                queue = pregen_queues.get(context_str, [])
                already_filled = len(queue) >= 1

            if already_filled:
                continue

            all_filled = False
            print(f"\n[Restocker] Pre-generating joke for String #{i}...", flush=True)

            prompt = f"Original NPC text: '{context_str}'\nRewrite this as a short, funny joke.\nJoke:"
            messages = [{"role": "user", "content": prompt}]

            with generator_lock:
                try:
                    result = generator(messages, max_new_tokens=30, temperature=0.8, do_sample=True)
                    raw = result[0]['generated_text'][-1]['content']
                    new_text = _clean_llm_output(raw)
                    new_text = _truncate_to_word_boundary(new_text)

                    if new_text:
                        with state_lock:
                            if context_str not in pregen_queues:
                                pregen_queues[context_str] = []
                            pregen_queues[context_str].append(new_text)
                        print(f"[Restocker] String #{i} stocked.", flush=True)
                except Exception as e:
                    print(f"[Restocker] Failed: {e}", flush=True)

        if all_filled:
            time.sleep(0.5)


# Start background restocker
threading.Thread(target=background_restocker, daemon=True).start()


# --- Main NPC Text Handler ---

def generate_npc_text(original_text):
    global proximity_index

    if len(original_text) < 3:
        return "IGNORE_TEXT"

    npc_key = original_text
    print(f"[NPC Key] '{npc_key[:60]}...'", flush=True)

    now = time.time()

    with state_lock:
        last_seen = interacted_npcs.get(npc_key, None)

    if last_seen is not None:
        elapsed = now - last_seen

        if elapsed < CONVERSATION_COOLDOWN:
            # Same conversation — NPC animation, multi-part text, etc.
            print(f"[Memory] Same conversation ({elapsed:.1f}s ago). Native text continues.", flush=True)
            return "IGNORE_TEXT"

        # Genuine return visit!
        print(f"[Memory] Return visit ({elapsed:.0f}s since last). Serving AI joke!", flush=True)
        with state_lock:
            interacted_npcs[npc_key] = now
            queue = pregen_queues.get(npc_key, [])
            joke = queue.pop(0) if queue else None

        if joke:
            print("[Queue Pop] Instant Hit! (0.00s Latency)", flush=True)
            threading.Thread(target=generate_joke_for, args=(npc_key,), daemon=True).start()
            return paginate_text(joke)

        # Queue miss — generate on the fly
        print("[Queue Miss] Generating on the fly...", flush=True)
        prompt = f"Original NPC text: '{npc_key}'\nRewrite this as a short, funny joke.\nJoke:"
        messages = [{"role": "user", "content": prompt}]

        with generator_lock:
            try:
                result = generator(messages, max_new_tokens=25, temperature=0.8, do_sample=True)
                raw = result[0]['generated_text'][-1]['content']
                new_text = _clean_llm_output(raw)
                new_text = _truncate_to_word_boundary(new_text)
                if not new_text:
                    return "IGNORE_TEXT"
                return paginate_text(new_text)
            except Exception as e:
                print(f"[Error] On-the-fly generation failed: {e}", flush=True)
                return "IGNORE_TEXT"

    # First interaction — let native text play, cache joke in background
    print("[Memory] First interaction! Native text plays. Caching joke in background...", flush=True)
    with state_lock:
        interacted_npcs[npc_key] = now
    threading.Thread(target=generate_joke_for, args=(npc_key,), daemon=True).start()
    return "IGNORE_TEXT"


# --- TCP Server Loop ---

def make_response(new_dialogue):
    """Encode response and pad to 1024 bytes with 0x00 (NOT 0x7F which is Gen 1 space!)."""
    if new_dialogue == "IGNORE_TEXT":
        raw = b"IGNORE_TEXT"
    else:
        raw = charmap.encode(new_dialogue)
    if len(raw) < 1024:
        raw = raw + bytes([0x00] * (1024 - len(raw)))
    return raw


while True:
    try:
        print(f"Waiting for mGBA to connect on port {PORT}...", flush=True)
        conn, addr = server_sock.accept()
        print("mGBA Connected! Bridge established.", flush=True)

        # Do NOT clear memory on reconnect.
        # This allows bridge.lua to safely drop the connection to flush
        # late TCP data without losing the session's memory of interacted NPCs.
        print("[Connection] Ready to process requests.", flush=True)

        recv_buffer = b""

        with conn:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break

                recv_buffer += chunk

                # Process all complete messages (delimited by 0x0A newline sent by bridge.lua)
                while b"\n" in recv_buffer:
                    message_bytes, recv_buffer = recv_buffer.split(b"\n", 1)

                    if not message_bytes:
                        continue

                    original_decoded = charmap.decode(message_bytes)
                    original_text = original_decoded.strip()

                    if not original_text:
                        conn.sendall(make_response("IGNORE_TEXT"))
                        continue

                    print(f"\n[Intercepted] {original_text[:80]}", flush=True)

                    new_dialogue = generate_npc_text(original_text)

                    if new_dialogue != "IGNORE_TEXT":
                        print(f"[AI Generated] \"{new_dialogue.replace(chr(1), '<PARA>').replace(chr(10), '<LINE>')}\"", flush=True)

                    conn.sendall(make_response(new_dialogue))

        print("mGBA disconnected. Waiting for reconnect...", flush=True)

    except Exception as e:
        print(f"Server error: {e}", flush=True)
