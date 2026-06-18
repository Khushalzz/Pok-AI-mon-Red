# -*- coding: utf-8 -*-
# charmap.py
# A complete Gen 1 Character Encoding dictionary for Pokemon Red/Blue (English)

char_to_hex = {
    ' ': 0x7F,
    '0': 0xF6, '1': 0xF7, '2': 0xF8, '3': 0xF9, '4': 0xFA,
    '5': 0xFB, '6': 0xFC, '7': 0xFD, '8': 0xFE, '9': 0xFF,
    '!': 0xE7, '?': 0xE6, '.': 0xE8, '-': 0xE3, "'": 0xE0,
    ',': 0xF4, '/': 0xF3, ':': 0x9C, ';': 0x9D,
    '(': 0x9A, ')': 0x9B,
    '\u2642': 0xEF,  # male sign (Gen 1 byte EF)
    '\u2640': 0xF5,  # female sign (Gen 1 byte F5)
    '\xd7': 0xF1,    # multiplication sign x
    # POKe abbreviation glyph (renders as "POKe" in-game)
    '#': 0x54,
    # e with acute accent (as in POKeMON, Pokedex) -- 0xBA in Gen 1
    '\xe9': 0xBA,
}

# Add uppercase letters (A=0x80, Z=0x99)
for i in range(26):
    char_to_hex[chr(ord('A') + i)] = 0x80 + i

# Add lowercase letters (a=0xA0, z=0xB9)
for i in range(26):
    char_to_hex[chr(ord('a') + i)] = 0xA0 + i

# Control codes
char_to_hex['\n'] = 0x4F    # LINE (next line in textbox)
char_to_hex['\x01'] = 0x51  # PARA (clear box, wait for press)
char_to_hex['\x02'] = 0x55  # CONT (scroll continuation)

# Create the reverse mapping
hex_to_char = {v: k for k, v in char_to_hex.items()}
# 0x4E is also a line break (used outside standard textbox context)
hex_to_char[0x4E] = '\n'

def decode(byte_array):
    """Decodes a byte array from Gen 1 encoding to a Python string."""
    result = ""
    for byte in byte_array:
        if byte in (0x50, 0x57, 0x58):  # Terminators: @, DONE, PROMPT
            break
        if byte in hex_to_char:
            result += hex_to_char[byte]
        else:
            result += " "  # Replace unknown with space
    return result

def encode(text):
    """Encodes a Python string into a Gen 1 byte array, terminating with 0x50."""
    result = []
    for char in text:
        if char in char_to_hex:
            result.append(char_to_hex[char])
        else:
            result.append(char_to_hex.get('?', 0xE6))
    result.append(0x50)  # Append Gen 1 terminator @
    return bytes(result)
