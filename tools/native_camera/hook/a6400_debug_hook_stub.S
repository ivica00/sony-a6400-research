@ a6400 runtime ARM probe trampoline (E0401, Phase 2 offline prototype).
@
@ The installer copies the 32-bit instruction at the hooked kernel address into
@ a6400_hook_saved_instruction and writes an ARM B to a6400_hook_stub at the
@ hooked address. The stub captures r0-r12/sp/lr/cpsr plus one configured
@ pointer dereference into a fixed 96-byte record, restores the interrupted
@ register and flag state, executes the saved instruction, and continues at
@ saved_pc+4.
@
@ All addresses the stub needs are absolute values in the literal slots below;
@ the installer fills them (and the saved instruction) and calls
@ flush_icache_range over the touched code after every install and rollback.
@
@ Record layout (24 words / 96 bytes, little-endian):
@   0 magic 'A64H'       1 sequence        2 tick counter (installer-provided)
@   3..18 r0..r12, sp, lr, cpsr (16 words)
@   19 dereference address (0 when disabled)
@   20 dereference value (0 when disabled)
@   21..23 reserved (ring writer sets CRC/type/length)
.syntax unified
.arm
.section .text.a6400_hook_stub, "ax", %progbits
.global a6400_hook_stub
.type a6400_hook_stub, %function
a6400_hook_stub:
    stmdb   sp!, {r0-r12, lr}
    mrs     r0, cpsr
    str     r0, [sp, #-4]!

    ldr     r12, a6400_hook_ring_next_slot
    ldr     r12, [r12]
    ldr     r0, a6400_hook_magic_slot
    str     r0, [r12], #4
    ldr     r1, a6400_hook_seq_slot
    ldr     r2, [r1]
    add     r3, r2, #1
    str     r3, [r1]
    str     r2, [r12], #4
    ldr     r1, a6400_hook_ticks_slot
    ldr     r2, [r1]
    str     r2, [r12], #4

    add     r3, sp, #4
    mov     r4, #13
1:  ldr     r5, [r3], #4
    str     r5, [r12], #4
    subs    r4, r4, #1
    bne     1b
    add     r5, sp, #60            @ interrupted sp (14 registers + cpsr)
    str     r5, [r12], #4
    ldr     r5, [sp, #56]          @ interrupted lr (r0-r12 occupy 52 bytes)
    str     r5, [r12], #4
    ldr     r5, [sp]               @ interrupted cpsr
    str     r5, [r12], #4

    ldr     r4, a6400_hook_config_slot
    ldr     r5, [r4]
    cmp     r5, #0
    beq     2f
    ldr     r5, [r4, #4]           @ captured register index 0..15
    add     r6, sp, #4
    add     r6, r6, r5, lsl #2
    ldr     r6, [r6]
    ldr     r7, [r4, #8]           @ byte offset
    add     r6, r6, r7
    str     r6, [r12], #4
    ldr     r7, [r6]               @ pointer dereference
    str     r7, [r12], #4
    b       3f
2:  mov     r5, #0
    str     r5, [r12], #4
    str     r5, [r12], #4
3:  mov     r5, #0
    str     r5, [r12], #4
    str     r5, [r12], #4
    str     r5, [r12], #4

    ldr     r4, a6400_hook_ring_next_slot
    ldr     r5, a6400_hook_ring_limit_slot
    ldr     r5, [r5]
    cmp     r12, r5
    blo     4f
    ldr     r5, a6400_hook_ring_base_slot
    ldr     r12, [r5]
4:  str     r12, [r4]

    ldr     r5, [sp]
    msr     cpsr_f, r5
    add     sp, sp, #4
    ldmia   sp!, {r0-r12, lr}
    ldr     pc, a6400_hook_exec_slot

.global a6400_hook_saved_instruction
.type a6400_hook_saved_instruction, %function
a6400_hook_saved_instruction:
    nop
    ldr     pc, a6400_hook_target_next_slot

@ Absolute-address slots. Installer writes these before the target patch and
@ restores the saved instruction to nop on rollback.
.align 2
.global a6400_hook_ring_next_slot
a6400_hook_ring_next_slot:  .word 0
.global a6400_hook_ring_base_slot
a6400_hook_ring_base_slot:  .word 0
.global a6400_hook_ring_limit_slot
a6400_hook_ring_limit_slot: .word 0
.global a6400_hook_seq_slot
a6400_hook_seq_slot:        .word 0
.global a6400_hook_ticks_slot
a6400_hook_ticks_slot:      .word 0
.global a6400_hook_config_slot
a6400_hook_config_slot:     .word 0
.global a6400_hook_magic_slot
a6400_hook_magic_slot:      .word 0
.global a6400_hook_exec_slot
a6400_hook_exec_slot:       .word 0
.global a6400_hook_target_next_slot
a6400_hook_target_next_slot: .word 0

.section .note.GNU-stack, "", %progbits
