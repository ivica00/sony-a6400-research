# E0170 — Izvorni OSAL izvršitelj korisničkih povratnih poziva

Datum: 2026-11-08. Offline nastavak E0169. Bez pristupa kameri i promjena produkcijskog modula.

## Izvori i izvršenje

Novi `tools/research/probe_uvc_ptp_osal_dispatch.py` izvršava originalni registracijski put u a6400 libosal_uipc.so, originalni callback worker i originalni registrirani USB callback iz libUsbControl.so u zasebnoj adresnoj regiji. Obje biblioteke i ELF relokacije provjerene su prije izvršenja.

| Izvor | SHA-256 |
|---|---|
| libosal_uipc.so | b6ded35add9582413b401cf4db78ec2c9a201b632e78c2731d6bbb379249b3eb |
| libUsbControl.so | 70cd5742fde9eea78c60905e4015531b4c3ab2668d2cb85c934531f451f1211f |

## Registracija Sonyjeve obavijesti

Originalni osal_reg_msg_queue_cb na 0x4301 provjerava bit 0x8000 ID-a. Za stvarni statički ID iz E0169, 0x00e942cd, bit nije postavljen: originalni kod odlazi u u_osal_reg_msg_queue_cb na 0x2749, a ne u lokalni callback-list put.

Taj put priprema ioctl 0x80000008: vanjski par je `{queue_id, pointer_to_stack_fields}`, a unutarnji podaci `{output_handle_pointer, callback_pointer, user_argument, 0}`. Pokus provjerava točan ID, callback, argument i oblik paketa te staje prije ioctl servisa. Registracija u kernelu i stvaranje worker dretve nisu izvršeni.

Negativni lokalni ID i lokalni ID s null callbackom vraćaju 0xfffffc00 iz originalnih guardova. To su odvojene negativne provjere; ne predstavljaju pogrešku na stvarnom Sonyjevu ID-u.

## Worker

Statički izvorni put na 0x1c58..0x1c66 priprema pthread_create i izračuna start rutinu 0x2031. Provjereni su stvarna PLT relokacija za pthread_create i literal koji daje start adresu. Sam pthread_create nije izvršen i nema potvrde fizičkog TID-a.

Originalna rutina 0x2031 preko ioctl 0x8000000d traži posao. Par predan ioctl-u je `{0, pointer_to_16_byte_descriptor}`. Povratni descriptor ima raspored:

| Pomak | Izvorno korišteno polje |
|---|---|
| +0 | callback funkcija |
| +4 | callback r1 |
| +8 | callback r0 |
| +12 | indeks workera, zadan pri pokretanju |

Za eksplicitni kernel-output fixture worker poziva stvarni USB callback 0x131a5 iz druge biblioteke s točnim argumentima. Callback učita `{operation=1,status=-5}`, preda ih builderu poruke (izričita servisna zamjena), zatim preda izvornu poruku osal_free_msg (izričita zamjena) za ID 0x00e942cd. Tek nakon povratka callbacka originalni worker ponovno ulazi u ioctl 0x8000000d. Drugi ioctl je granica zaustavljanja.

Pokus također provjerava originalnu granu ponavljanja na -1021: callback se ne izvodi prije uspješnog drugog primitka, indeks workera ostaje očuvan i nakon callbacka slijedi novi wait zahtjev.

Originalni worker stoga može izvršavati callback neovisno o Main petlji iz E0169. To je dokaz predviđenog odvojenog izvršitelja u kodu, a ne dokaz trenutačnog rasporeda fizičkih dretava, jedinstvenog workera ili potpune zaštite promjene USB načina.

## Kernel granica za daljnju provjeru

Statički pregled originalnog a6400 osal_uipc.ko (ranije zadržan SHA-256 `3743275bc964a2804b80cde4f589f60876b795fbeeccd3cbf2c18a0da2dc8567`) identificira `__k_4u_wait_cb` na .text+0xe8c. Sljedeći wait poziv obrađuje prethodni callback zapisan u per-worker slotu, pa slijedi novi posao. U tom putu postoje grane prema wake_up_process ili finish_callback. `unreg_msg_queue_cb` i helper na .text+0x27a0 koriste dodatne oznake callbacka i čekanje. Ova kernel tijela nisu izvršena u E0170: ne smije se pretpostaviti da unregister automatski znači završen callback ili da je samo uklanjanje korisničkog pokazivača dovoljno.

## Rezultat i granice

**16 provjera prolazi**. Manifest: `artifacts/analysis/uvc-ptp-osal-e0170/manifest.json`; zapis: `artifacts/uvc-ptp-osal-e0170.log`.

Kernel ioctl odgovor, file descriptor 17, worker index 3 i poruka izričiti su fixture podaci. Naming/cancellation/memset, builder ObjMsg i free servisi su izričite zamjene. Izvorne biblioteke odlučuju o granama, rasporedu argumenata, povratku callbacka i ponavljanju. Guardovi odbijaju neočekivano izvršavanje i zapise. Nema fizičke registracije, raspoređivača ni kernel čišćenja u ovom pokusu.

Sljedeća konkretna provjera je kernel potvrda dovršetka prethodnog callbacka i ponašanje unregister-a dok je callback aktivan. E0164 ostaje neučitan i `physical_test_ready:false`. Nema novog senzorskog UVC dokaza; posljednja puna projektna regresija ostaje 605 testova jer produkcijski modul nije mijenjan.
