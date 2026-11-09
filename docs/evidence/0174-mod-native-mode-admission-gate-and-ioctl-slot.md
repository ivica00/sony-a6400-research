# E0174 — MOD atomska zaštita promjene načina i izvorni ioctl ulaz

Datum: 2026-11-08. Offline implementacija. Nema prijenosa ili zapisa na kameru. E0164 kernel modul nije promijenjen.

## Implementacija

Novi `tools/native_camera/uvc_ptp_mode_gate.{c,h}` implementira **MOD pravilo pristupa**, ne zamjenu Sonyjevih odluka. Jedna atomska riječ sadrži broj aktivnih izvornih ulaza ili ekskluzivno vlasništvo MOD transakcije. CAS 0→HELD uklanja razmak između provjere aktivnih ulaza i preuzimanja transakcije.

| Operacija | Ugovor |
|---|---|
| mode_enter | Poveća broj aktivnih ulaza ako MOD ne drži transakciju. Odbije HELD i preljev. |
| mode_leave | Smanji aktivni broj bez zadiranja u HELD. Odbije nulu i HELD stanje. |
| mode_claim | Preuzme transakciju isključivo iz stanja 0. |
| mode_release | Oslobodi isključivo točno HELD stanje. Ne briše broj tuđih aktivnih ulaza. |

Enter/leave imaju ograničen broj CAS pokušaja i u slučaju konflikta vraćaju busy. Pozivatelj ne smije ignorirati neuspješan leave niti tvrditi da je transakcija tada oslobođena. Null ulazi i dvostruko oslobađanje odbijaju se. Struktura mora trajati kroz sve ulaze; kod ne daje samostalno pravo uklanjanja hooka ili oslobađanja memorije.

## Izgradnja i provjere

`tools/research/build_uvc_ptp_mode_gate.py` izgrađuje stvarni ARMv7 softfp ELF bez libc/importa i izvršava prevedene funkcije. Rezultat: `artifacts/native/uvc-ptp-mode-gate-e0174/mode-gate.elf`. Manifest u istoj mapi sadrži hashove izvora/headera/ELF-a i točan build argument vector. Zapis: `artifacts/uvc-ptp-mode-gate-e0174.log`.

**28 provjera prolazi**: 22 provjere MOD atomskih funkcija i šest provjera izvornog kernel ulaza. Provjerena su dva aktivna izvorna ulaza, oba redoslijeda nadmetanja s MOD claimom, očuvanje broja pri odbijenom release-u, overflow i nepravilna HELD+count stanja. Ovo su sekvencijalna izvršenja ARM atomskih instrukcija; nisu fizički multicore pokus ili dokaz kompletnog Linux memory-model ugovora.

Izgradnja je prvo odbijena zbog preklapanja GNU build-id sekcije s odabranom offline adresom teksta; konačni reproducibilni builder izričito isključuje build-id. To ne mijenja tijela MOD funkcija niti native kernel.

## Dokazan izvorni ulaz

SHA-provjereni kernel `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707` sadrži:

- `usb_gcore_module_init` na 0x604a580c;
- originalni LDR r1 na 0x604a590c čita literal 0x604a5990 = **0x604e5078**;
- sljedeći originalni BL na 0x604a5910 poziva `cdev_init` na 0x601c241c;
- file operations +0x20, adresa **0x604e5098**, pokazuje na izvorni `usb_gadgetcore_ioctl` **0x602b8844**;
- susjedni open +0x2c i release +0x34 odgovaraju 0x602b8814 i 0x602b8284.

Ovo vezuje kandidat za ulaz na stvarni cdev_init ugovor, a ne samo na slučajno pronađenu riječ u kernel slici. Nije izvršena izmjena te adrese. Live RAM sadržaj i mogućnost sigurne objave/uklanjanja posrednika nisu provjereni.

## Integracijski uvjeti koji ostaju otvoreni

Gate je `integrated:false`. Svi relevantni izvorni ulazi moraju stvarno prolaziti kroz njega; današnji modulov lokalni gate ne čini to. Poziv koji je već učitao stari function pointer, module lifetime pri objavi wrappera, izravni kernel izvozi, USB disconnect/suspend i EP0 callbackovi ne smiju se pretpostaviti pokrivenima samo ovim file-operations slotom.

Za prvi test preostaju sigurna objava/vlasništvo posrednika za izvorne promjene USB načina i završetak/drain native gadget/EP0 callbackova, zatim ograničen activate/restore runner. Gate se ne smije uključiti slijepim RAM zapisom. OSAL acknowledgment dokazi E0172 rješavaju zaseban profil callbacka; nisu automatski EP0 ugovor.

Trenutačna read-only provjera kamere E0173 (`artifacts/hardware/uvc-ptp-readiness-e0173/usb-current.json`) potvrdila je PC Remote 054c:0caa. Nije mijenjan način rada. Produkcijski `.ko` ostaje E0164, neučitan i `physical_test_ready:false`. Zadnja puna projektna regresija ostaje 605 testova; za novi izolirani ARM dio izvršene su gore navedene ciljane provjere.
