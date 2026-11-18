; ---- console: PC keyboard + direct video memory, ADM-3A / Kaypro codes
;  (shared with pocket8086-cpm; see README for the codes)
;  Entered through the wrapper: DS = CS, private stack.

f_CONST:
        call    syncur
        mov     ah, 01h
        int     16h
        mov     al, 0
        jz      .r
        mov     al, 0FFh
.r:     ret

f_CONIN:
        call    syncur
.again: xor     ah, ah
        int     16h
        or      al, al
        jnz     .r
        mov     dl, ah                  ; extended key: map its scan code
        mov     si, keymap
.m:     lodsw                           ; al = scan code, ah = character
        or      al, al
        jz      .again                  ; unmapped key: ignore it
        cmp     al, dl
        jne     .m
        mov     al, ah
.r:     ret

; move the hardware cursor to our cursor position if it changed
syncur:
        cmp     byte [cdirty], 0
        je      .r
        mov     byte [cdirty], 0
        mov     ah, 02h
        xor     bh, bh
        mov     dh, [crow]
        mov     dl, [ccol]
        int     10h
.r:     ret

; first output: find the video buffer and pick up the BIOS cursor
; (preserves CX: CL holds the character being written)
con_init:
        push    cx
        push    es
        xor     ax, ax
        mov     es, ax
        mov     word [vseg], 0B800h
        cmp     byte [es:449h], 7       ; monochrome text mode?
        jne     .c
        mov     word [vseg], 0B000h
.c:     mov     ax, [es:44Ah]           ; columns
        cmp     ax, 40
        jb      .c80
        cmp     ax, 132
        jbe     .cok
.c80:   mov     ax, 80
.cok:   mov     [ncols], ax
        mov     al, [es:484h]           ; rows-1 (EGA/VGA BIOS), else 0
        inc     al
        cmp     al, 24
        jb      .r25
        cmp     al, 60
        jbe     .rok
.r25:   mov     al, 25
.rok:   mov     [nrows], al
        mov     ax, [es:44Eh]           ; start of the active page
        mov     [vbase], ax
        pop     es
        mov     ah, 03h
        xor     bh, bh
        int     10h
        mov     [crow], dh
        mov     [ccol], dl
        mov     byte [cinit], 1
        pop     cx
        ret

f_CONOUT:
        cmp     byte [cinit], 0
        jne     .go
        call    con_init
.go:    mov     byte [cdirty], 1
        mov     al, cl
        and     al, 7Fh
        mov     ah, [escstate]
        or      ah, ah
        jnz     con_esc
        cmp     al, 7Fh
        je      .r                      ; DEL: nothing
        cmp     al, 20h
        jae     con_print
        mov     bl, al                  ; control character: jump table
        xor     bh, bh
        shl     bx, 1
        jmp     [ctltab+bx]
.r:     ret

con_print:
        push    ax
        call    vaddr                   ; (uses AX)
        pop     ax
        mov     ah, [cattr]
        stosw
        inc     byte [ccol]
        mov     al, [ccol]
        cmp     al, [ncols]
        jb      .r
        mov     byte [ccol], 0
        jmp     c_lf
.r:     ret

c_ignore:
        ret
c_bel:
        mov     ax, 0E07h
        mov     bx, 0007h
        int     10h
        ret
c_bs:
        cmp     byte [ccol], 0
        je      .r
        dec     byte [ccol]
.r:     ret
c_tab:
        mov     al, [ccol]
        add     al, 8
        and     al, 0F8h
        mov     ah, [ncols]
        dec     ah
        cmp     al, ah
        jbe     .s
        mov     al, ah
.s:     mov     [ccol], al
        ret
c_lf:
        inc     byte [crow]
        mov     al, [crow]
        cmp     al, [nrows]
        jb      .r
        dec     byte [crow]
        xor     al, al
        jmp     del_line                ; scroll up
.r:     ret
c_up:
        cmp     byte [crow], 0
        je      .r
        dec     byte [crow]
.r:     ret
c_right:
        mov     al, [ccol]
        inc     al
        cmp     al, [ncols]
        jae     .r
        mov     [ccol], al
.r:     ret
c_cr:
        mov     byte [ccol], 0
        ret
c_home:
        mov     word [crow], 0          ; crow and ccol
        ret
c_cls:
        mov     word [crow], 0
c_eos:
        call    vaddr
        mov     al, [nrows]
        mul     byte [ncols]
        shl     ax, 1
        add     ax, [vbase]
        sub     ax, di
        shr     ax, 1
        mov     cx, ax
        jmp     blank
c_eol:
        call    vaddr
        mov     cl, [ncols]
        sub     cl, [ccol]
        xor     ch, ch
blank:
        mov     ax, 0720h
        cld
        rep     stosw
        ret
c_esc:
        mov     byte [escstate], 1
        ret

; escape sequences
con_esc:
        mov     byte [escstate], 0
        cmp     ah, 1
        jne     .s2
        cmp     al, '='
        je      .pos
        cmp     al, 'B'
        je      .aon
        cmp     al, 'C'
        je      .aoff
        cmp     al, 'E'
        je      .ins
        cmp     al, 'R'
        je      .del
        cmp     al, 'T'
        je      c_eol
        cmp     al, 'Y'
        je      c_eos
        cmp     al, '*'
        je      c_cls
        ret
.pos:   mov     byte [escstate], 2
        ret
.aon:   mov     byte [escstate], 4
        ret
.aoff:  mov     byte [escstate], 5
        ret
.ins:   mov     al, [crow]
        jmp     ins_line
.del:   mov     al, [crow]
        jmp     del_line
.s2:    cmp     ah, 2
        jne     .s3
        sub     al, 20h
        mov     [escrow], al
        mov     byte [escstate], 3
        ret
.s3:    cmp     ah, 3
        jne     .s4
        sub     al, 20h                 ; column
        mov     ah, [ncols]
        dec     ah
        cmp     al, ah
        jbe     .c1
        mov     al, ah
.c1:    mov     [ccol], al
        mov     al, [escrow]
        mov     ah, [nrows]
        dec     ah
        cmp     al, ah
        jbe     .c2
        mov     al, ah
.c2:    mov     [crow], al
        ret
.s4:    cmp     ah, 4
        jne     .s5
        mov     ah, 70h                 ; ESC B 0: reverse
        cmp     al, '0'
        je      .sa
        mov     ah, 0Fh                 ; ESC B 1: bright
        cmp     al, '1'
        je      .sa
        ret
.s5:    cmp     al, '0'                 ; ESC C 0 / ESC C 1: back to normal
        je      .norm
        cmp     al, '1'
        jne     .r
.norm:  mov     ah, 07h
.sa:    mov     [cattr], ah
.r:     ret

; vaddr: ES:DI = video address of (crow, ccol)
vaddr:
        mov     al, [crow]
        mul     byte [ncols]
        add     al, [ccol]
        adc     ah, 0
        shl     ax, 1
        add     ax, [vbase]
        mov     di, ax
        mov     es, [vseg]
        ret

; rowaddr: AL = row -> AX = video offset of its first character
rowaddr:
        mul     byte [ncols]
        shl     ax, 1
        add     ax, [vbase]
        ret

; del_line: AL = row; rows below move up one, last row blanked
del_line:
        mov     bl, al
        call    rowaddr
        mov     di, ax                  ; destination: row r
        mov     ax, [ncols]
        shl     ax, 1
        mov     si, di
        add     si, ax                  ; source: row r+1
        mov     al, [nrows]
        dec     al
        sub     al, bl                  ; rows to move
        mul     byte [ncols]
        mov     cx, ax
        mov     es, [vseg]
        push    ds
        mov     ds, [vseg]
        cld
        rep     movsw
        pop     ds
        mov     cx, [ncols]             ; DI is now at the last row
        jmp     blank

; ins_line: AL = row; it and the rows below move down one, row blanked
ins_line:
        mov     bl, al
        mov     al, [nrows]
        dec     al
        sub     al, bl
        mul     byte [ncols]
        mov     cx, ax                  ; words to move
        mov     al, [nrows]
        dec     al
        call    rowaddr                 ; start of last row
        mov     di, ax
        add     di, [ncols]
        add     di, [ncols]
        sub     di, 2                   ; last word of the last row
        mov     ax, [ncols]
        shl     ax, 1
        mov     si, di
        sub     si, ax                  ; last word of the row above
        mov     es, [vseg]
        push    ds
        mov     ds, [vseg]
        std
        rep     movsw
        cld
        pop     ds
        mov     al, bl
        call    rowaddr
        mov     di, ax
        mov     cx, [ncols]
        jmp     blank

ctltab  dw      c_ignore, c_ignore, c_ignore, c_ignore  ; 00-03
        dw      c_ignore, c_ignore, c_ignore, c_bel     ; 04-07
        dw      c_bs,     c_tab,    c_lf,     c_up      ; 08-0B
        dw      c_right,  c_cr,     c_ignore, c_ignore  ; 0C-0F
        dw      c_ignore, c_ignore, c_ignore, c_ignore  ; 10-13
        dw      c_ignore, c_ignore, c_ignore, c_eos     ; 14-17 (^W)
        dw      c_eol,    c_ignore, c_cls,    c_esc     ; 18-1B (^X ^Z ESC)
        dw      c_ignore, c_ignore, c_home,   c_ignore  ; 1C-1F (^^)

