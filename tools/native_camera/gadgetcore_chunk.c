/* E0405b: 64-byte EP0 chunk framing helpers executed under Unicorn.
 * Frames are 4096 bytes; chunks are <=64 bytes. Return the copied byte count
 * or 0xffffffff on a bounds/prototype violation. No external calls. */
typedef unsigned int u32;
typedef unsigned char u8;

u32 a6400_chunk_extract(const u8 *frame, u32 frame_len, u32 index, u8 *out)
{
    u32 offset, count, i;
    if (!frame || !out)
        return 0xffffffffu;
    offset = index * 64u;
    if (offset >= frame_len)
        return 0;
    count = frame_len - offset;
    if (count > 64u)
        count = 64u;
    for (i = 0; i < count; i++)
        out[i] = frame[offset + i];
    return count;
}

u32 a6400_chunk_insert(u8 *frame, u32 frame_cap, u32 index, const u8 *in, u32 in_len)
{
    u32 offset, i;
    if (!frame || !in)
        return 0xffffffffu;
    if (in_len > 64u)
        in_len = 64u;
    offset = index * 64u;
    if (offset + in_len > frame_cap)
        return 0xffffffffu;
    for (i = 0; i < in_len; i++)
        frame[offset + i] = in[i];
    return in_len;
}
