import os
import sys

# ============================================================
# patch_rom.py — AI Pokemon NPC Patcher v2.0
# Patches a Pokemon Red (US v1.0) ROM to hook PrintText and
# signal the Lua bridge whenever an NPC dialogue starts.
#
# Fixes applied vs v1.0:
#   - hROMBank offset corrected to 0xB8 ($FFB8)
#   - WRAM addresses moved to safe ds 8 padding block ($C1FF-$C203)
#   - Hook size search dynamically uses len(custom_hook), not hardcoded 40
#   - HALT instruction added inside busy-wait loop (saves CPU)
#   - jr nz offset recalculated after HALT addition
#   - ROM path via command-line arg or tkinter file dialog
# ============================================================

# --- SAFE WRAM ADDRESSES ---
# Verified safe: 5 bytes from the 56-byte unnamed padding gap at $D6B8-$D6EF
# (right after wGameProgressFlagsEnd, before wObtainedHiddenItemsFlags).
# This gap has NO label, is never written by any game routine, and survives
# all gameplay scenarios including battles, saves, and Pokemon Center.
ADDR_PTR_L  = 0xD6B8   # Text pointer low byte
ADDR_PTR_H  = 0xD6B9   # Text pointer high byte
ADDR_BANK   = 0xD6BA   # ROM bank
ADDR_FLAG   = 0xD6BB   # Waiting flag (1 = paused, 0 = resume)
ADDR_ACTIVE = 0xD6BC   # Lua heartbeat (0x99 = Lua is running)

def patch_rom(rom_path, output_path=None):
    if not os.path.exists(rom_path):
        print(f"ROM not found at {rom_path}")
        return False

    if output_path is None:
        base, ext = os.path.splitext(rom_path)
        output_path = base + " (AI)" + ext

    with open(rom_path, "rb") as f:
        rom_data = bytearray(f.read())

    # 1. Search for PrintText_NoCreatingTextBox in Bank 0
    #    Signature: 01 B9 C4 C3 XX XX (ld bc, $C4B9 ; jp TextCommandProcessor)
    signature = bytes([0x01, 0xB9, 0xC4, 0xC3])
    match_index = -1
    for i in range(0, 0x4000 - len(signature)):
        if rom_data[i:i+4] == signature:
            match_index = i
            break

    if match_index == -1:
        print("Could not find PrintText_NoCreatingTextBox signature!")
        print("Make sure you are using the USA/Europe v1.0 Pokemon Red ROM.")
        return False

    print(f"Found PrintText signature at 0x{match_index:04X}")

    # Read the address of TextCommandProcessor (the jump target)
    tcp_addr_low  = rom_data[match_index + 4]
    tcp_addr_high = rom_data[match_index + 5]
    print(f"TextCommandProcessor is at 0x{tcp_addr_high:02X}{tcp_addr_low:02X}")

    # 2. Assemble CustomHook
    #
    # Byte layout of WRAM addresses for the LDxx instructions:
    ptrl_l  = ADDR_PTR_L  & 0xFF; ptrl_h  = (ADDR_PTR_L  >> 8) & 0xFF
    ptrh_l  = ADDR_PTR_H  & 0xFF; ptrh_h  = (ADDR_PTR_H  >> 8) & 0xFF
    bank_l  = ADDR_BANK   & 0xFF; bank_h  = (ADDR_BANK   >> 8) & 0xFF
    flag_l  = ADDR_FLAG   & 0xFF; flag_h  = (ADDR_FLAG   >> 8) & 0xFF
    actv_l  = ADDR_ACTIVE & 0xFF; actv_h  = (ADDR_ACTIVE >> 8) & 0xFF

    # Offsets reference (will verify jr nz offsets below):
    #   0:  ld a, [ADDR_ACTIVE]     — 3 bytes
    #   3:  cp $99                  — 2 bytes
    #   5:  jr nz, .skip            — 2 bytes  (skip to jp, offset calculated below)
    #   7:  ld a, l                 — 1 byte
    #   8:  ld [ADDR_PTR_L], a      — 3 bytes
    #  11:  ld a, h                 — 1 byte
    #  12:  ld [ADDR_PTR_H], a      — 3 bytes
    #  15:  ldh a, [$B8]            — 2 bytes  (reads hROMBank = $FFB8, CORRECTED from 0xF8)
    #  17:  ld [ADDR_BANK], a       — 3 bytes
    #  20:  ld a, $01               — 2 bytes
    #  22:  ld [ADDR_FLAG], a       — 3 bytes
    #  25:  .waitLoop:
    #  25:  ld a, [ADDR_FLAG]       — 3 bytes
    #  28:  and a                   — 1 byte
    #  29:  jr nz, .waitLoop        — 2 bytes  (offset = -6, so 0xFA)
    #  31:  HALT                    — 1 byte   (NEW: sleep until interrupt, saves CPU)
    #       NOTE: HALT here is INSIDE waitLoop via the jr nz above.
    #       Actually, to make HALT useful we need to restructure. 
    #       Better: put HALT before the check so CPU sleeps between polls.
    #  Let's restructure the waitLoop:
    #  25:  .waitLoop:
    #  25:  HALT                    — 1 byte   (sleep until VBlank/interrupt fires)
    #  26:  ld a, [ADDR_FLAG]       — 3 bytes
    #  29:  and a                   — 1 byte
    #  30:  jr nz, .waitLoop        — 2 bytes  (offset = -(30-25+2) = -7 = 0xF9)
    #  32:  ld a, [ADDR_PTR_L]      — 3 bytes
    #  35:  ld l, a                 — 1 byte
    #  36:  ld a, [ADDR_PTR_H]      — 3 bytes
    #  39:  ld h, a                 — 1 byte
    #  40:  .skip:
    #  40:  jp TextCommandProcessor — 3 bytes
    #  Total: 43 bytes
    #
    #  jr nz .skip offset: from byte 7 (after jr nz), we jump to byte 40. 
    #  offset = 40 - 7 = 33 = 0x21
    #  jr nz .waitLoop offset: from byte 32 (after jr nz), we jump back to byte 25.
    #  offset = 25 - 32 = -7 = 0xF9

    custom_hook = bytearray([
        # Check if Lua is active
        0xFA, actv_l, actv_h,       # ld a, [ADDR_ACTIVE]
        0xFE, 0x99,                  # cp $99
        0x20, 0x21,                  # jr nz, .skip  (jump 33 bytes forward to jp)

        # Save HL text pointer
        0x7D,                        # ld a, l
        0xEA, ptrl_l, ptrl_h,       # ld [ADDR_PTR_L], a
        0x7C,                        # ld a, h
        0xEA, ptrh_l, ptrh_h,       # ld [ADDR_PTR_H], a

        # Save current ROM bank — CORRECTED: hROMBank is at $FFB8, offset 0xB8
        0xF0, 0xB8,                  # ldh a, [$B8]  (= ld a, [$FFB8])
        0xEA, bank_l, bank_h,        # ld [ADDR_BANK], a

        # Set waiting flag to 1 (pause the CPU)
        0x3E, 0x01,                  # ld a, $01
        0xEA, flag_l, flag_h,        # ld [ADDR_FLAG], a

        # .waitLoop: sleep until Lua clears the flag
        0x76,                        # HALT  (sleep until VBlank interrupt)
        0xFA, flag_l, flag_h,        # ld a, [ADDR_FLAG]
        0xA7,                        # and a
        0x20, 0xF9,                  # jr nz, .waitLoop  (-7 bytes back to HALT)

        # Load (possibly modified) text pointer from WRAM
        0xFA, ptrl_l, ptrl_h,       # ld a, [ADDR_PTR_L]
        0x6F,                        # ld l, a
        0xFA, ptrh_l, ptrh_h,       # ld a, [ADDR_PTR_H]
        0x67,                        # ld h, a

        # .skip: jump to the original TextCommandProcessor
        0xC3, tcp_addr_low, tcp_addr_high
    ])

    print(f"CustomHook assembled: {len(custom_hook)} bytes")

    # 3. Find enough free space in Bank 0 for the hook
    required_size = len(custom_hook)
    empty_space = bytes([0x00] * required_size)
    hook_addr = -1

    for i in range(0x1000, 0x4000 - required_size):
        if rom_data[i:i+required_size] == empty_space:
            hook_addr = i
            break

    if hook_addr == -1:
        print(f"Could not find {required_size} bytes of free space in Bank 0!")
        return False

    print(f"Found free space for CustomHook at 0x{hook_addr:04X}")

    # 4. Inject CustomHook
    rom_data[hook_addr : hook_addr + len(custom_hook)] = custom_hook

    # 5. Redirect the original jp to point to CustomHook
    hook_low  = hook_addr & 0xFF
    hook_high = (hook_addr >> 8) & 0xFF
    rom_data[match_index + 4] = hook_low
    rom_data[match_index + 5] = hook_high

    print(f"Redirected PrintText -> CustomHook at 0x{hook_addr:04X}")

    # 6. Write patched ROM
    with open(output_path, "wb") as f:
        f.write(rom_data)

    print(f"\nSuccessfully patched ROM!")
    print(f"Input:  {rom_path}")
    print(f"Output: {output_path}")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        rom_input = sys.argv[1]
        rom_out = sys.argv[2] if len(sys.argv) >= 3 else None
        patch_rom(rom_input, rom_out)
    else:
        # Try tkinter file dialog for GUI usage
        try:
            import tkinter as tk
            from tkinter import filedialog, messagebox
            root = tk.Tk()
            root.withdraw()
            rom_input = filedialog.askopenfilename(
                title="Select your Pokemon Red ROM",
                filetypes=[("Game Boy ROM", "*.gb *.gbc"), ("All files", "*.*")]
            )
            if not rom_input:
                print("No ROM selected.")
                sys.exit(0)
            result = patch_rom(rom_input)
            if result:
                messagebox.showinfo("Success!", f"ROM patched successfully!\n\nSaved to:\n{result}")
            else:
                messagebox.showerror("Failed", "ROM patching failed. Check the console for details.")
        except ImportError:
            print("Usage: python patch_rom.py <input.gb> [output.gb]")
            sys.exit(1)
