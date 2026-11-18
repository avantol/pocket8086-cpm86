; ---------------------------------------------------------------------------
;  CP/M-86 1.1 BIOS for the Pocket8086 (any 8086/8088/V20/V30 PC with an
;  INT 13h hard disk - here the CF/SD card)
;
;  CP/M-86 "8080 model": the CCP and BDOS occupy offsets 0000h-24FFh of one
;  segment (DR's CPM.H86); this BIOS follows at 2500h in the same segment.
;  The boot sector loads the whole image to SYSSEG:0000 and jumps to INIT
;  with DL = boot drive.
;
;  Every BIOS entry that calls the PC BIOS switches to a private stack, so
;  the BDOS's small stack is never at risk.
;
;  Assemble: nasm -f bin -I build/ bios86.asm -o bios86.bin
; ---------------------------------------------------------------------------
        bits    16
        cpu     8086
        org     2500h

%include "layout.inc"           ; NDISKS, SPT, drive tables (from build.py)

CCP      equ    0000h
BDOS_OFS equ    0B06h           ; BDOS entry point in CPM.H86 1.1
BDOS_INT equ    0E0h            ; INT 224: CP/M-86 system call

; ---- BIOS jump vector (each entry 3 bytes) -------------------------------
        jmp     near INIT
        jmp     near WBOOT
        jmp     near CONST
        jmp     near CONIN
        jmp     near CONOUT
        jmp     near LISTOUT
        jmp     near PUNCH
        jmp     near READER
        jmp     near HOME
        jmp     near SELDSK
        jmp     near SETTRK
        jmp     near SETSEC
        jmp     near SETDMA
        jmp     near READ
        jmp     near WRITE
        jmp     near LISTST
        jmp     near SECTRAN
        jmp     near SETDMAB
        jmp     near GETSEGT
        jmp     near GETIOBF
        jmp     near SETIOBF

; ---- cold start -----------------------------------------------------------
INIT:
        cli
        mov     ax, cs
        mov     ds, ax
        mov     es, ax
        mov     ss, ax
        mov     sp, stack_top
        sti
        cld
        mov     [bootdrv], dl

        xor     ax, ax                  ; INT E0h -> BDOS entry
        mov     es, ax
        mov     word [es:BDOS_INT*4], BDOS_OFS
        mov     [es:BDOS_INT*4+2], cs
        push    ds
        pop     es

        mov     ah, 08h                 ; disk geometry for LBA -> CHS
        mov     dl, [bootdrv]
        push    es
        int     13h
        pop     es
        jc      .nogeo
        and     cx, 003Fh
        jz      .nogeo
        mov     [spt], cx
        mov     al, dh
        xor     ah, ah
        inc     ax
        mov     [heads], ax
.nogeo:
        ; memory region table: one region from the end of the BIOS to the
        ; top of conventional memory (INT 12h, which already excludes any
        ; memory an option ROM has reserved)
        mov     bx, bios_end + 15
        mov     cl, 4
        shr     bx, cl
        mov     ax, cs
        add     bx, ax
        mov     [mrt_base], bx
        int     12h                     ; AX = KB
        mov     cl, 6
        shl     ax, cl                  ; -> paragraphs
        sub     ax, bx
        mov     [mrt_len], ax

        mov     si, signon
        call    pmsg
        mov     ax, [mrt_len]           ; "nnnK TPA"
        mov     cl, 6
        shr     ax, cl
        call    pdec
        mov     si, signon2
        call    pmsg
        mov     byte [inbios], 0        ; from now on BIOS calls switch stacks
        mov     cl, 0                   ; drive A:
        jmp     CCP                     ; (the CCP sets its own SP; SS = CS)

WBOOT:
        jmp     CCP+6                   ; CCP command level

; print a 0-terminated string at DS:SI through CONOUT
pmsg:
        lodsb
        or      al, al
        jz      .r
        push    si
        mov     cl, al
        call    CONOUT
        pop     si
        jmp     pmsg
.r:     ret

; print AX in decimal
pdec:
        xor     dx, dx
        mov     bx, 10
        div     bx
        push    dx
        or      ax, ax
        jz      .out
        call    pdec
.out:   pop     ax
        add     al, '0'
        mov     cl, al
        jmp     CONOUT

; ---- entries that need the PC BIOS: run them on our own stack -------------
%macro  WRAPPED 1
%1:     mov     word [cs:fnptr], f_%1
        jmp     wrapper
%endmacro

        WRAPPED CONST
        WRAPPED CONIN
        WRAPPED CONOUT
        WRAPPED LISTOUT
        WRAPPED PUNCH
        WRAPPED READER
        WRAPPED LISTST
        WRAPPED READ
        WRAPPED WRITE

wrapper:
        cmp     byte [cs:inbios], 0     ; already on our stack (INIT, pmsg)?
        jne     .direct
        mov     byte [cs:inbios], 1
        mov     [cs:save_ss], ss
        mov     [cs:save_sp], sp
        cli
        mov     ax, cs
        mov     ss, ax
        mov     sp, stack_top
        sti
        push    ds
        push    es
        push    si
        push    di
        push    bp
        mov     ds, ax
        cld
        call    [fnptr]
        pop     bp
        pop     di
        pop     si
        pop     es
        pop     ds
        cli
        mov     ss, [cs:save_ss]
        mov     sp, [cs:save_sp]
        sti
        mov     byte [cs:inbios], 0
        ret
.direct:
        push    ds
        push    es
        push    si
        push    di
        push    bp
        mov     ax, cs
        mov     ds, ax
        cld
        call    [fnptr]
        pop     bp
        pop     di
        pop     si
        pop     es
        pop     ds
        ret

; ---- simple entries (no PC BIOS calls) -----------------------------------
HOME:
        mov     word [cs:track], 0
        ret
SELDSK:                                 ; CL = drive -> BX = DPH or 0
        xor     bx, bx
        cmp     cl, NDISKS
        jae     .r
        mov     [cs:drive], cl
        mov     bl, cl
        mov     cl, 4
        shl     bx, cl
        add     bx, dpbase
.r:     ret
SETTRK:
        mov     [cs:track], cx
        ret
SETSEC:
        mov     [cs:sector], cx
        ret
SETDMA:
        mov     [cs:dma_off], cx
        ret
SETDMAB:
        mov     [cs:dma_seg], cx
        ret
SECTRAN:                                ; no skew on a flash card
        mov     bx, cx
        ret
GETSEGT:
        mov     bx, mrt
        ret
GETIOBF:
        mov     al, [cs:iobyte]
        ret
SETIOBF:
        mov     [cs:iobyte], cl
        ret

; ---- printer (LPT1) and serial (COM1) -------------------------------------
f_LISTOUT:
        mov     al, cl
        xor     ah, ah
        xor     dx, dx
        int     17h
        ret
f_LISTST:
        mov     ah, 02h
        xor     dx, dx
        int     17h
        mov     al, 0
        test    ah, 80h                 ; 1 = not busy
        jz      .r
        mov     al, 0FFh
.r:     ret
f_PUNCH:
        mov     al, cl
        mov     ah, 01h
        xor     dx, dx
        int     14h
        ret
f_READER:
        mov     ah, 02h
        xor     dx, dx
        int     14h
        test    ah, 80h                 ; timeout?
        jz      .r
        mov     al, 1Ah                 ; return ^Z (end of file)
.r:     ret

%include "console.inc"
%include "disk.inc"

; ---- data --------------------------------------------------------------------
signon   db     13, 10, 'CP/M-86 1.1 for the Pocket8086', 13, 10
         db     DRIVES_MSG, ', ', 0
signon2  db     'K TPA', 13, 10, 0

; memory region table (GETSEGT)
mrt      db     1
mrt_base dw     0
mrt_len  dw     0

bootdrv  db     0
spt      dw     17
heads    dw     4
iobyte   db     0
fnptr    dw     0
save_ss  dw     0
save_sp  dw     0
inbios   db     1                       ; 1 during INIT (already on our stack)
drive    db     0
track    dw     0
sector   dw     0
dma_off  dw     0
dma_seg  dw     0
recoff   dw     0
diskop   db     0
cvalid   db     0
clba     dd     0

; console state
escstate db     0
escrow   db     0
vseg     dw     0B800h
vbase    dw     0
ncols    dw     80
nrows    db     25
crow     db     0                       ; crow, ccol: keep together
ccol     db     0
cattr    db     07h
cinit    db     0
cdirty   db     0

keymap   db     48h, 05h                ; up     -> ^E
         db     50h, 18h                ; down   -> ^X
         db     4Bh, 13h                ; left   -> ^S
         db     4Dh, 04h                ; right  -> ^D
         db     53h, 7Fh                ; Del    -> DEL
         db     0, 0

        DRIVE_TABLES                    ; drv_base (dd), drv_tracks (dw)
        DISK_TABLES                     ; dpbase, DPHs, DPBs

image_end:

; ---- uninitialised data (not in the image) ---------------------------------
        section .bss
        alignb  16
cache    resb   512                     ; host sector buffer
dirbuf   resb   128
        DISK_BSS                        ; allocation vectors
        alignb  2
         resb   768                     ; BIOS stack
stack_top:
        alignb  16
bios_end:
