-- AI Pokemon NPC Bridge v2.0
-- Intercepts NPC dialogue in Pokemon Red and routes it through the Python AI server.
-- Fixes: battle text filter (wIsInBattle), pcall error recovery, socket timeout,
--        is_generating cleanup, correct buffer start (no TX_END prefix).

local host = "127.0.0.1"
local port = 8000
local sock = nil

function connect_server()
    if sock then return true end
    for attempt = 1, 5 do
        sock = socket.connect(host, port)
        if sock then 
            console:log("Bridge established! Connected to Python.")
            return true 
        end
        console:log("Connecting to Python server... attempt " .. attempt .. "/5")
        local t0 = os.clock()
        while os.clock() - t0 < 0.3 do end
    end
    console:error("Bridge failed: Could not connect to Python. Is server.py running?")
    return false
end

connect_server()

-- mGBA's socket implementation does not support settimeout.
-- We will rely on the server padding to exactly 1024 bytes so receive(1024) unblocks.

console:log("Bridge established! Native ROM Hook active.")

-- ============================================================
-- WRAM Addresses used by our CustomHook (patch_rom.py)
-- 56-byte unnamed padding gap at $D6B8-$D6EF (verified safe):
-- after wGameProgressFlagsEnd, never used by any game routine
-- ============================================================
local ADDR_PTR_L  = 0xD6B8  -- Text pointer low byte
local ADDR_PTR_H  = 0xD6B9  -- Text pointer high byte
local ADDR_BANK   = 0xD6BA  -- ROM bank
local ADDR_FLAG   = 0xD6BB  -- Waiting flag (1 = paused, 0 = resume)
local ADDR_ACTIVE = 0xD6BC  -- Lua heartbeat (0x99 = Lua is running)

-- Buffer in WRAM where we write the AI text
-- $D428 is in wSerialPlayerDataBlock; safe during single-player gameplay
local TEXT_BUFFER_START = 0xD428

-- Game state addresses (confirmed from pokered-master/ram/wram.asm)
local ADDR_IS_IN_BATTLE = 0xD057  -- wIsInBattle: 0=overworld, 1=wild, 2=trainer

-- Tell the ROM that Lua is active!
emu:write8(ADDR_ACTIVE, 0x99)

local is_generating = false

-- ============================================================
-- read_rom_text: reads raw Gen 1 bytes from ROM at a pointer
-- ============================================================
function read_rom_text(ptr)
    local t = ""
    local curr_ptr = ptr

    local first_byte = emu:read8(curr_ptr)
    local orig_bank = emu:read8(0xFFB8)  -- hROMBank at $FFB8 (confirmed from hram.asm)
    local new_bank = orig_bank

    -- Handle TX_FAR (0x17) — banked text pointer
    if first_byte == 0x17 then
        local new_ptr_l = emu:read8(curr_ptr + 1)
        local new_ptr_h = emu:read8(curr_ptr + 2)
        new_bank = emu:read8(curr_ptr + 3)
        curr_ptr = (new_ptr_h * 256) + new_ptr_l

        if new_bank ~= orig_bank then
            emu:write8(0x2000, new_bank)
        end
        first_byte = emu:read8(curr_ptr)
    end

    -- Skip TX_START (0x00) if present
    if first_byte == 0x00 then
        curr_ptr = curr_ptr + 1
    end

    -- Read text bytes until a terminator is hit
    -- 0x50 = @/End, 0x57 = DONE, 0x58 = PROMPT
    for i = 1, 500 do
        local b = emu:read8(curr_ptr)
        if b == 0x50 or b == 0x57 or b == 0x58 then break end
        t = t .. string.char(b)
        curr_ptr = curr_ptr + 1
    end

    -- Restore original ROM bank
    if new_bank ~= orig_bank then
        emu:write8(0x2000, orig_bank)
    end

    return t
end

-- ============================================================
-- cleanup: always called to unpause the game and reset state
-- ============================================================
function cleanup()
    emu:write8(ADDR_FLAG, 0x00)
    is_generating = false
end

-- ============================================================
-- intercept_frame_inner: the real logic (called inside pcall)
-- ============================================================
function intercept_frame_inner()
    -- Keep the Lua active flag alive every frame (survives soft-reset)
    emu:write8(ADDR_ACTIVE, 0x99)

    -- Only enter if the ROM hook has paused the game and we aren't already busy
    if emu:read8(ADDR_FLAG) ~= 1 or is_generating then
        return
    end

    if not connect_server() then
        cleanup()
        return
    end

    is_generating = true

    -- --------------------------------------------------------
    -- FILTER 1: Battle check
    -- wIsInBattle ($D057) is non-zero during ALL battles.
    -- Battle text must NEVER be intercepted — it would freeze combat.
    -- --------------------------------------------------------
    local is_in_battle = emu:read8(ADDR_IS_IN_BATTLE)
    if is_in_battle ~= 0 then
        console:log("In battle — skipping interception.")
        cleanup()
        return
    end

    -- --------------------------------------------------------
    -- FILTER 2: NPC sprite check
    -- hSpriteIndexOrTextID ($FF8C): sprite index for NPCs.
    -- wNumSprites ($D4E1): number of NPC sprites on the current map.
    -- If sprite_id is outside the valid NPC range, it's a sign/item/system message.
    -- --------------------------------------------------------
    local sprite_id   = emu:read8(0xFF8C)
    local num_sprites = emu:read8(0xD4E1)

    if sprite_id == 0 or sprite_id > num_sprites then
        console:log(string.format("Non-NPC text (ID %d > %d) — skipping.", sprite_id, num_sprites))
        cleanup()
        return
    end

    -- --------------------------------------------------------
    -- Valid NPC — read its text and send to Python
    -- --------------------------------------------------------
    local ptr_l = emu:read8(ADDR_PTR_L)
    local ptr_h = emu:read8(ADDR_PTR_H)
    local original_ptr = (ptr_h * 256) + ptr_l

    console:log(string.format("Intercepted NPC (Sprite: %d/%d) at 0x%04X", sprite_id, num_sprites, original_ptr))

    local original_text = read_rom_text(original_ptr)

    -- Send to Python (newline delimited so server can frame messages correctly)
    local ok, err = sock:send(original_text .. "\n")
    if not ok then
        console:error("Send failed: " .. tostring(err) .. " — dropping connection.")
        sock:close()
        sock = nil
        cleanup()
        return
    end

    -- mGBA's socket receive is completely non-blocking, so we must spin-wait
    -- until we get all 1024 bytes or hit a 5-second timeout.
    console:log("Waiting for AI response...")
    local data = ""
    local t0 = os.clock()
    
    while os.clock() - t0 < 5.0 do
        local chunk, recv_err, partial = sock:receive(1024 - #data)
        
        if chunk and #chunk > 0 then
            data = data .. chunk
        elseif partial and #partial > 0 then
            data = data .. partial
        end
        
        if #data == 1024 then
            break -- We got the full padded message!
        end
        
        if recv_err == "closed" then
            console:error("Python server disconnected!")
            sock:close()
            sock = nil
            cleanup()
            return
        end
    end

    if data and #data == 1024 then
        if string.find(data, "IGNORE_TEXT") then
            console:log("Python: native text (first visit or system text).")
        else
            console:log("AI Response received! Injecting into WRAM...")

            -- The game engine (TextCommandProcessor) expects a text command first.
            -- 0x00 is TX_START, which tells it to start printing the characters that follow.
            emu:write8(TEXT_BUFFER_START, 0x00)
            
            local i = 1
            while i <= #data do
                local b = string.byte(data, i)
                emu:write8(TEXT_BUFFER_START + i, b)
                if b == 0x50 then
                    -- PlaceString terminator (@) written.
                    -- Now write the script terminator (TX_END) right after it!
                    emu:write8(TEXT_BUFFER_START + i + 1, 0x50)
                    break
                end
                i = i + 1
            end

            -- Redirect the text pointer to our WRAM buffer
            emu:write8(ADDR_PTR_L, TEXT_BUFFER_START & 0xFF)
            emu:write8(ADDR_PTR_H, (TEXT_BUFFER_START >> 8) & 0xFF)
        end
    else
        console:error("Timeout reading AI response! Dropping connection to prevent late text desync.")
        sock:close()
        sock = nil
    end

    cleanup()
end

-- ============================================================
-- intercept_frame: safe wrapper with pcall for error recovery
-- ============================================================
function intercept_frame()
    local ok, err = pcall(intercept_frame_inner)
    if not ok then
        console:error("Bridge error: " .. tostring(err))
        -- Always unpause the game even if an error occurred!
        emu:write8(ADDR_FLAG, 0x00)
        is_generating = false
    end
end

callbacks:add("frame", intercept_frame)
