# E0175 — MOD omotač izvornog ioctl-a i zadržavanje aktivnog ulaza

Datum: 2026-11-08. Offline implementacija. Kamera nije kontaktirana. Produkcijski modul E0164 nije mijenjan.

## Kod

`tools/native_camera/uvc_ptp_ioctl_guard.{c,h}` povezuje atomski gate E0174 s pozivom stvarne izvorne ioctl funkcije. Kontekst sadrži gate, nepromjenjivi originalni function pointer i zapamćenu grešku. Omotač:

1. Provjerava kontekst, originalni cilj i prethodnu grešku.
2. Uđe kroz mode_enter prije izvornog poziva.
3. Proslijedi file/command/arg u izvornu funkciju.
4. Pozove mode_leave tek nakon njezina povratka i očuva izvorni rezultat.
5. Ako leave ne uspije, zapamti grešku i odbije buduće izvorne pozive, MOD claim i release. Izvorna operacija tada se već mogla dogoditi: ta pogreška ne znači da je sve vraćeno.

Ovo je MOD upravljanje pristupom. Ne zamjenjuje Sonyjeve odluke niti implementira prepoznavanje, video ili kontrole na hostu. Funkcija prima eksplicitni kontekst; nije objavljena kao native file_operations callback i ne mijenja kameru.

## Izgradnja i izvršenje

`python -m tools.research.build_uvc_ptp_mode_gate --ioctl-guard --output-dir artifacts/native/uvc-ptp-ioctl-guard-e0175`

Builder prevede oba MOD C dijela za ARMv7 softfp bez libc/uvoza. Izvršava stvarni prevedeni kod i odabrana originalna kernel tijela `usb_gadgetcore_ioctl` / test-and-set-bit iz SHA-provjerenog kernela `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`.

**42 provjere prolaze**: ranijih 28 i 14 dodatnih za omotač. Nepoznata originalna naredba očuva -25; commit dok je izvorni active bit postavljen očuva -16 i njegove flags. Ti izvorni putovi ne zovu kontroler ni copy servise.

Pokus se zaustavlja na ulazu originalne funkcije nakon što je omotač povećao count. Stvarni emulirani CPU kontekst ostaje sačuvan. Na odvojenom stogu MOD claim vraća busy. Nakon obnove konteksta originalna funkcija završi, omotač smanji count na nulu i očuva njezin rezultat. To potvrđuje trajanje pristupa kroz povratak izvorne funkcije; nije fizički multicore pokus.

Zasebni eksplicitni fault-injection fixture ukloni admission count dok izvorna funkcija radi. Leave to odbije, a omotač zapamti grešku i blokira dispatch/claim/release. Null kontekst i null original također se odbijaju. Fixture korupcija nije opažena kamera pogreška i ne predstavlja kompatibilnost Sonyjeva koda.

Manifest: `artifacts/native/uvc-ptp-ioctl-guard-e0175/manifest.json`; ELF: `mode-gate.elf` u istoj mapi; zapis: `artifacts/uvc-ptp-ioctl-guard-e0175.log`. Manifest sadrži hashove obaju C/header dijelova, ELF-a i kernel identitet. Provjerena je Python sintaksa buildera.

## Otvorena granica za postavljanje

`integrated:false` ostaje namjeran. Native slot 0x604e5098 potvrđen je u E0174, ali zamjena njegova pokazivača sama nije dokaz sigurne objave: postojeći poziv mogao je već učitati staru adresu. Moraju biti riješeni postojeći stari ulazi, trajanje wrapper koda/konteksta, njegovo kasnije uklanjanje i svi drugi izravni USB ulazi. `stop_machine` ili proizvoljno čekanje ne smiju se bez dokaza proglasiti završenim callback drainom.

Nijedna funkcija ovih novih datoteka ne instalira hook, ne uklanja hook i ne tvrdi da je native EP0/gadget završen. Sigurna objava i native callback drain ostaju konkretne prepreke fizičkom aktiviranju. E0164 `.ko` nije ponovno građen jer mu ovi dijelovi još nisu pridruženi; zadnja puna projektna regresija ostaje 605 testova, uz navedene nove ciljane ARM provjere.
