# E0164 — Zajednički PTP/UVC modul: izgradnja i zaštite životnog vijeka

Datum: 2026-11-08. Kamera nije kontaktirana u ovim provjerama. Nema prijenosa, učitavanja modula ni zapisa na kameru.

## Rezultat

Izgrađen je zaseban kandidat `artifacts/native/uvc-ptp-module-e0164/usbg_video_a6400_shared_candidate.ko`, 58.540 bajtova, SHA-256 `064fd44486824ea2e1d93729636b7d0408d73e332138f821c26fb6daf5ea952e`. Vermagic je `3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7 `. Manifest namjerno postavlja `deployable:false` i `physical_test_ready:false`.

Kandidat povezuje ranije provjerene deskriptore, upravljanje njihovom kopijom, sesiju i nativni backend s izvornim referentnim video modulom. PTP ostaje na sučelju 0, UVC koristi sučelja 1/2 i zasebni Bulk IN 0x82. Identitet se preuzima kroz izvorne Sonyjeve serijalizatore i strogo provjerava prije promjene konfiguracije. Stvarni RAM raspored identiteta još nije fizički provjeren.

Ovo je kandidat za enumeraciju. Registracija video međuspremnika, slanje kadrova i ostale video naredbe odbijaju se. START provjerava odabir endpointa, ali ne poziva izvorni video START. Modul ne dokazuje sliku senzora niti istodobnu Windows UVC/PTP komunikaciju.

## Zaštite

- `file_operations.owner` povezan je s `__this_module`; vlastiti izvoz omogućuje dodatno zadržavanje modula tijekom aktivne ili nepotpuno očišćene sesije.
- Omotači STOP i release prvo završavaju sesiju. Ako je čišćenje blokirano, preskaču izvorne funkcije koje bi oslobodile kontekst. Izvorni release inače zanemaruje pogrešku oslobađanja DMA i nastavlja oslobađati kontekst.
- Status ostaje dostupan u zadržanom stanju. Preklapanje ulazaka u ovaj modul odbija se atomarnom zaštitom.
- DMA provjera koristi oduzimanje nakon provjere minimalnog kapaciteta; `UINT_MAX` više ne može proći zbog preljeva pri zbrajanju duljine zaglavlja.
- Samo dvije izričito dokumentirane izvorne instrukcije promijenjene su u referentnom tekstu (tri različita bajta). Izvorni init/exit ostaju jednaki.

Ova zaštita ulazaka ne usklađuje neovisni Sonyjev zadatak za promjenu USB načina rada. Njegov ugovor zaključavanja mora biti utvrđen prije fizičkog pokusa. Neuspjeh pri vraćanju stanja zadržava resurse umjesto nagađanja vlasništva.

## Provjere i granice dokaza

`artifacts/analysis/uvc-ptp-module-e0164/manifest.json` bilježi 29 uspješnih provjera stvarno prevedenih omotača: povezivanje file operations, izvoz, odbijanje video naredbi, status, uredno prosljeđivanje zatvaranja, zadržano stanje i granice DMA duljine. Izvorni core ioctl/release i copy servisi u ovom pokusu izričiti su bilježnici poziva. Učitavač modula i stvarni brojači referenci nisu izvršeni.

Regresija nativnog backenda prolazi 147 provjera u `artifacts/native/uvc-ptp-native-regression-e0164`. Izvorni serijalizatori izvršavaju se u kontroliranom ARM okruženju; hardverski servisi imaju izričite zamjene. To nije fizički USB pokus.

Svih 47 uvoza pronađeno je u zadržanim dokazima o kernelu i modulima. Za osam uvoza iz `dma330.ko` i `osal_uipc.ko` dodatno su provjerena stvarna imena izvoza u izvornim ELF sekcijama `__ksymtab_strings`; rezultat i hashovi zapisani su u `artifacts/analysis/uvc-ptp-module-e0164/module-export-evidence.json`. Prisutnost u zadržanim datotekama ne dokazuje trenutačno stanje učitanih modula.

Prethodni zasebni način izgradnje s vlastitim koherentnim DMA i probe-only START-om također se uspješno izgrađuje. Projektni testovi: **605 prošlo, 15,406 s**, zapis `artifacts/uvc-ptp-module-e0164-project-tests.log`.

## Sljedeća granica

Prvo utvrditi izvorno usklađivanje promjena USB načina rada i trajanje callbackova, zatim pripremiti ograničen fizički pokus enumeracije s provjerljivim povratkom na PC Remote. Prijenos stvarnih senzorskih JPEG kadrova i prilagodba hostovog traženja zajedničkog uređaja ostaju zasebni nedovršeni koraci. E0150 statički uzorak pri 30 FPS ostaje dokaz transporta, ne senzorskog izvora.
