# E0161: Vlasništvo pri instalaciji i obnovi descriptor tablica

Datum: 2026-11-08. Nastavak E0160. Bez pristupa kameri.

## Implementacija

`tools/native_camera/uvc_ptp_descriptor_lease.{c,h}` uvodi zasebnu ownership
transakciju. Caller mora PRIJE poziva zaustaviti kontroler, povući callbackove,
držati topologiju zaključanom i pripremiti odgovarajući native address-limit
ugovor. Ti preduvjeti ovim helperom nisu implementirani niti dokazani.
Helper sam ne isključuje USB, ne registrira drivere i ne tvrdi quiescence.

Install prima12-byte originalni save argument ABI i dva ops pointera
(native save/free u budućoj integraciji). Prima samo predviđeni jedan HS/FS
kandidat bez extra/dual policy dodataka, verificira vlastito stablo i odbija
ponovljenu aktivnu instalaciju.

Prije native save poziva sprema originalni PC Remote root, flags i byteove
84/85. Zatim gc+6c postavlja na nulu: originalna save failure grana tako ne
može preko free_desc_tbl dobiti prethodnu PC Remote tablicu. Nakon save-a
zasebno bilježi installed root. Success zahtijeva ne-null native kopiju
različitu od stare tablice i caller templatea, te uspješan E0160 validator.

Pri native erroru uz null root vraća izvorni root/flags/mode i izvorni error.
Success s null rootom vraća -5 i također obnavlja snapshot.
Neočekivani alias, nevaljana kopija ili error koji ostavi neočekivani root
prelazi u QUARANTINED. Source objekt ostaje zadržan; nema slijepog free poziva.

Restore radi samo za INSTALLED stanje i točno zabilježeni aktivni root.
Provjerava i identitet free operacije. Oslobađa samo novu native kopiju,
potvrđuje da je native free nulirao gc+6c, zatim vraća izvorni root/flags/mode
i čisti ownership zapis. Ponavljanje restorea nakon uspjeha je idempotentno.
Tuđi root vraća -116 bez oslobađanja. Free koji prekrši null-root ugovor
prelazi u quarantine i ne ponavlja se; time se izbjegava mogući double free.

`a6400_descriptor_source_releasable` vraća1 samo za EMPTY stanje. Time
budući modul može spriječiti oslobađanje templatea dok je transakcija aktivna
ili nepoznata. Module-unload zaštita još nije povezana s tim rezultatom.

## Granice provjere i stvarni originalni ulaz

`tools.research.build_uvc_ptp_descriptor_lease` gradi stvarni samostalan ARM
ELF zajedno s descriptor validatorom. Source/header/ELF hashovi i hashovi
ulaznog template/copy fixturea vezani su u manifestima.

U transakcijskim testovima save/free su IZRIČITI RECORD DOUBLEOVI. Oni
postavljaju provjereni neovisni descriptor fixture i vraćaju zadane greške;
to nisu native allocator ili fizički controller acknowledgementi. Stvarno
se izvršavaju kompajlirani ownership helper i validator, a zapisi su guardani.

73 provjere prolaze. Obuhvaćaju dva uzastopna ciklusa, error/null-success
obnovu, zaštitu stare tablice, held-source stanje, duplu instalaciju,
ponovljeni restore, stare/source aliase, nevaljanu kopiju, tuđi aktivni root,
promijenjeni free callback i neispravan free ugovor.

Dodatni pokret ulazi iz stvarnog ownership helpera u ORIGINALNI a6400
save_desc_tbl602bc550. Izvršavanje staje na602bc598 PRIJE __copy_from_user,
bez izmišljenog copy/allocator povrata. U toj točki potvrđeni su originalni
save argument pointer, sačuvani stari root u ownership objektu, gc+6c=0 i
INSTALLING stanje. Cijeli native save ne vraća se i instalacija nije proglašena
uspješnom. Thread address-limit i memorija su eksplicitni offline fixturei.

## Artefakti

- `artifacts/native/uvc-ptp-lease-input-e0161/`:573 prethodne descriptor
  kontrole, owned template i neovisni copy fixture s hashovima.
- `artifacts/native/uvc-ptp-descriptor-lease-e0161/manifest.json`:73 ownership
  provjere i svi source/ELF/input hashovi.
- `descriptor-lease.elf`:offline ARM izvršni artefakt, NIJE kernel modul.

```
python -m tools.research.build_uvc_ptp_descriptor_lease --input-dir artifacts/native/uvc-ptp-lease-input-e0161 --output-dir artifacts/native/uvc-ptp-descriptor-lease-e0161
```

## Nastavak integracije

Treba povezati stvarni controller quiesce i lock, native save/free wrapper
s ispravnim address limitom, UVC shadow registraciju, EP0 hook i reconnect.
Tek tada je dopušteno tvrditi da ownership helper obnavlja fizički PC Remote.
Treba dokazati source/module lifetime dok su native callbackovi aktivni i
oporavak iz quarantinea; nema automatskog fizičkog recovery koda u ovom koraku.

Originalni PTP driver još nije uključivan/isključivan u zajedničkoj fizičkoj
konfiguraciji. Native JPEG/DMM producer i senzorski UVC video ostaju otvoreni.
Puni projektni runtime nije mijenjan pa prethodni605 testovi nisu ponavljani.
Nema kamera uploadova, modula, feeder procesa, USB promjene, SD ili trajnih
zapisa. Istovremeni fizički UVC+PTP i dalje nije potvrđen.
