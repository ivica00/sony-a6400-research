.syntax unified
.arm
.global _start
.type _start,%function
_start:
    mov r0, #0
    mov r1, #0
    bl main
    mov r7, #1
    svc #0
    b .
.section .note.GNU-stack,"",%progbits
