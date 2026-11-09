/* Offline target-specific bypass for a future entry hook, NOT installed.
 * Reproduce the two original instructions, including the saved PC value,
 * before resuming untouched original gadgetcore ioctl at +8. */
    .syntax unified
    .arm
    .text
    .align 2
    .global a6400_uvc_native_ioctl_tail
    .type a6400_uvc_native_ioctl_tail,%function
a6400_uvc_native_ioctl_tail:
    mov ip,sp
    push {r4,r5,r6,r7,fp,ip,lr,pc}
    ldr ip,.Lsaved_pc
    str ip,[sp,#28]
    ldr ip,[sp,#20]
    ldr pc,.Lresume
.Lsaved_pc: .word 0x602b8850
.Lresume: .word 0x602b884c
    .size a6400_uvc_native_ioctl_tail,.-a6400_uvc_native_ioctl_tail
    .section .note.GNU-stack,"",%progbits
