# Pok-AI-mon Red: Dynamic LLM NPCs 🕹️🤖

This project hijacks the text engine of the original Game Boy **Pokémon Red** to replace every single NPC dialogue line with dynamic, witty, and contextual text generated on-the-fly by a local Large Language Model (LLM)!

No romhacks required. No pre-rendered text. Real-time LLM inference injected directly into the Game Boy's RAM!

## 🚀 How It Works

This project intercepts the Game Boy at the emulator level and routes the text through a custom AI pipeline:

1. **Memory Hijacking (`bridge.lua`)**: Runs inside the mGBA emulator. It places an execution hook directly on the Game Boy's `TextCommandProcessor`. When an NPC is about to speak, it pauses the emulator, intercepts the ROM text pointer, and sends the data to our local Python server.
2. **Text Decoding (`charmap.py`)**: The Game Boy does not use standard ASCII. It uses a proprietary Gen 1 character map. Our script seamlessly translates Game Boy hex values back and forth into standard UTF-8 text for the AI to read.
3. **AI Inference (`server.py`)**: We feed the decoded dialogue into an ultra-fast, local Small Language Model (like `SmolLM2-360M`). The AI evaluates the context and generates a completely original response.
4. **Game Boy Word Wrapping**: The Game Boy text box can only fit 18 characters per line. The Python server dynamically word-wraps the AI's response, injecting precise assembly-level control codes (`0x4F` for Line Breaks, `0x51` for Paragraph breaks) to prevent text-engine softlocks.
5. **Memory Injection**: The perfectly formatted response is forcefully injected back into the Game Boy's WRAM. It is terminated with double `@` (`0x50`) commands to safely resume the `TextCommandProcessor` and unpause the emulator!

## 🧠 The Training Pipeline

To make the AI funny and lore-accurate, this repository also features an enterprise-grade fine-tuning pipeline designed for Kaggle to train a custom LoRA adapter.

- **Hybrid Dataset Generation**: Uses a dual-model approach to rewrite the game's original 1,959 unique text strings. It aggressively utilizes the massive 70-Billion parameter **Llama-3.3-70B** via the Groq API for maximum quality, and seamlessly falls back to a local **Qwen2.5-7B** model on dual T4 GPUs to bypass strict API rate limits without pausing!
- **PokeAPI RAG**: The pipeline hooks into `PokeAPI` to perform live Retrieval-Augmented Generation. When it scans Game Boy text, it automatically downloads live elemental typings for any mentioned Pokémon and injects it into the prompt so the AI's jokes are highly context-aware.

## ⚙️ How to Run

1. **Launch the Single-Click GUI:**
   - Double-click `start_ai_pokemon.bat` on Windows.
   - The GUI will automatically install all necessary Python dependencies!

2. **Patch Your ROM:**
   - In the launcher, click **🔧 Patch ROM** and select your original, unmodified Pokémon Red (USA, v1.0) Game Boy ROM.
   - The launcher will safely inject the CustomHook into an empty WRAM padding block ($D6B8) and generate a `PokemonRed (AI).gb` file.

3. **Start the AI Server:**
   - In the launcher, click **▶️ Start Server**.
   - The server will dynamically pre-generate text for upcoming towns and load the local language model.

4. **Connect the Emulator:**
   - Open your **newly patched `(AI).gb` ROM** in the **mGBA emulator**.
   - Open the **Scripting Window** (`Tools` > `Scripting`).
   - Copy the Lua script path from the launcher, and load `bridge.lua` in mGBA.
   - Click **Run**!

5. **Talk to an NPC!**
   - **First Visit**: The NPC speaks their classic, native dialogue (e.g. "PROF. OAK, next door..."). Behind the scenes, the Python server instantly logs the interaction and generates a joke.
   - **Second Visit**: Walk away and talk to them again. The game seamlessly replaces their text pointer with our WRAM buffer, printing out a completely unique, AI-generated response!
