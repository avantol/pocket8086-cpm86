; ---- disk: 128-byte CP/M records on 512-byte card sectors -----------------
;  Track = 64 records = 16 card sectors.  One-sector cache, write-through.
;  Entered through the wrapper: DS = CS, private stack.

f_READ:
        call    calc_lba
        jc      dskerr
        call    fetch
        jc      dskerr
        mov     si, cache
        add     si, [recoff]
        les     di, [dma_off]           ; ES:DI = DMA (dma_off, dma_seg)
        mov     cx, 64
        rep     movsw
        xor     al, al
        ret
dskerr:
        mov     al, 1
        ret

f_WRITE:
        call    calc_lba
        jc      dskerr
        call    fetch
        jc      dskerr
        mov     di, cache
        add     di, [recoff]
        push    ds
        pop     es                      ; ES = BIOS segment
        push    ds
        lds     si, [dma_off]           ; DS:SI = DMA
        mov     cx, 64
        rep     movsw
        pop     ds
        mov     ah, 03h
        call    diskio
        jc      .bad
        xor     al, al
        ret
.bad:
        mov     byte [cvalid], 0
        jmp     dskerr

; calc_lba: drive/track/sector -> DX:AX = absolute LBA, [recoff]
calc_lba:
        mov     bl, [drive]
        cmp     bl, NDISKS
        jae     .bad
        xor     bh, bh
        mov     ax, [sector]
        cmp     ax, SPT
        jae     .bad
        mov     cl, 7
        mov     dx, ax
        and     dx, 3
        shl     dx, cl
        mov     [recoff], dx            ; (sector & 3) * 128
        shl     bx, 1
        mov     ax, [track]
        cmp     ax, [drv_tracks+bx]
        jae     .bad
        mov     cl, 4
        shl     ax, cl                  ; track * 16 card sectors
        mov     dx, [sector]
        shr     dx, 1
        shr     dx, 1
        add     ax, dx
        shl     bx, 1
        xor     dx, dx
        add     ax, [drv_base+bx]
        adc     dx, [drv_base+bx+2]
        clc
        ret
.bad:
        stc
        ret

; fetch: make sure card sector DX:AX is in the cache
fetch:
        cmp     byte [cvalid], 0
        je      .load
        cmp     ax, [clba]
        jne     .load
        cmp     dx, [clba+2]
        jne     .load
        clc
        ret
.load:
        mov     byte [cvalid], 0
        mov     [clba], ax
        mov     [clba+2], dx
        mov     ah, 02h
        call    diskio
        jc      .r
        mov     byte [cvalid], 1
.r:     ret

; diskio: AH = 02h (read) / 03h (write) sector [clba] <-> cache
diskio:
        push    es
        mov     [diskop], ah
        mov     ax, [clba]
        mov     dx, [clba+2]
        cmp     dx, [spt]
        jae     .fail                   ; quotient would overflow
        div     word [spt]
        inc     dx
        mov     cl, dl                  ; sector (1-based)
        xor     dx, dx
        div     word [heads]            ; ax = cylinder, dx = head
        cmp     ax, 1024
        jae     .fail
        mov     dh, dl
        mov     ch, al
        ror     ah, 1
        ror     ah, 1
        and     ah, 0C0h
        or      cl, ah
        mov     dl, [bootdrv]
        push    ds
        pop     es
        mov     bx, cache
        mov     di, 4
.try:
        mov     ah, [diskop]
        mov     al, 1
        push    cx
        push    dx
        int     13h
        pop     dx
        pop     cx
        jnc     .ok
        xor     ah, ah
        int     13h
        dec     di
        jnz     .try
.fail:
        stc
.ok:
        pop     es
        ret
