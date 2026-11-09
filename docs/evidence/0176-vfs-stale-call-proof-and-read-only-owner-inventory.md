# E0176 — Već učitan VFS poziv i read-only popis USB vlasnika

Datum: 2026-11-08. Nastavak E0175. Nema instalacije hooka, prijenosa payload-a, promjene USB načina ili zapisa na kameru.

## Izvorni VFS ugovor

`tools/research/probe_uvc_ptp_vfs_publication.py` SHA-provjerava originalni kernel i izvršava `vfs_ioctl` na 0x601ce2b0. Izvorni kod čita file+0x10, zatim file_operations+0x20 na 0x601ce2cc i poziva učitani pokazivač preko BLX r3 na 0x601ce2d8.

U eksplicitnom interleaving fixtureu izvršavanje staje prije BLX, nakon učitavanja starog cilja. Test promijeni slot na novi cilj i nastavi izvorni CPU kontekst. Poziv odlazi u stari cilj; tek sljedeći izvorni VFS poziv koristi novi cilj. File/fops su fixture objekti, a ciljevi izričiti return recorders; ne predstavljaju fizički hook ili Sonyjevu promjenu konfiguracije.

**10 provjera prolazi**. Izvještaj: `artifacts/analysis/uvc-ptp-publication-e0176/manifest.json`. Potvrđeni su i file/command/argument predaja i vraćanje rezultata. Zamjena jednog pokazivača nije sama po sebi pokrivanje već učitanog poziva. Činjenica da wrapperov novi broj ulaza iznosi nula također ne broji takav stari poziv.

## Točan izvorni uređaj

Provjerena je originalna init devnode referenca: literal 0x604a5988 pokazuje na zapis 0x604dab9c; ime na +0x18 je `usb/gadgetcore`, a polja +0x1e/+0x20/+0x22 daju major **242**, minor **1**, count **1**. To nije video node 248:33.

## Izgrađen read-only alat

`tools/native_camera/uvc_ptp_owner_inventory.c` izgrađen je u `artifacts/native/uvc-ptp-owner-inventory-e0176/uvc_ptp_owner_inventory`, **3376 bajtova**, SHA-256 `38aede0fa7969b3aa7119c155c884d77c93b15d9062ff47a08bbaf5240ebd2f7`.

Freestanding ARMv7 softfp ELF nema libc/interpreter ovisnost. Koristi samo read-only open, getdents64, stat64, close, stdout write i exit. Prvo provjeri `/dev/usb/gadgetcore` kao character 242:1, zatim po device broju traži otvorene FD-ove u `/proc`, pa popiše dretve procesa-vlasnika. Ne koristi readlink naziv kao dokaz identiteta FD-a, ne zaustavlja dretve i ne piše datoteke. `writes=0` u njegovu protokolu znači da ne mijenja datoteke/uređaj; tekstualni izvještaj šalje na stdout.

Rezultat je **observational=1**, čak i kad nema grešaka. Nestali FD/proces ili malformed directory record prijavljuju grešku; postoje granice broja procesa, FD-ova i dretava. Opažanje vlasnika nije atomarna snimka ni dokaz da novi proces ne može otvoriti uređaj.

Prva izgradnja odbijena je zbog compilerova division helpera. Konačni izvor pretvara brojeve bez runtime dijeljenja i ne treba libgcc/libc. U ELF-u nema PT_INTERP. Alat nije prenesen niti pokrenut na kameri.

## Provjera alata

`tools/research/audit_uvc_ptp_owner_inventory.py` izvršava stvarni prevedeni ARM alat uz izričite proc/stat syscall fixtures. **23 provjere prolaze**: točan owner po rdev-u, njegove dretve, završni sažetak, zatvaranje direktorija, pogrešan node prije proc čitanja, nedostupan proc, malformed dirent i nestali FD s nepotpunim rezultatom. Svaki dopušteni syscall provjerava se; ptrace, kill, ioctl i write-open nisu dopušteni.

Manifesti su u `artifacts/native/uvc-ptp-owner-inventory-e0176/manifest.json` i `artifacts/analysis/uvc-ptp-owner-inventory-e0176/manifest.json`. Proc i stat podaci su eksplicitni test fixturei, ne podaci trenutačne kamere.

## Trenutačna pristupačnost

Read-only pokušaj `python -m tools.camera_debugger info` vratio je: `Expected one existing MSC/MTP camera; found 0. No mode switch attempted.` U trenutačnom PC Remote načinu taj postojeći debugger kanal nije dostupan. To nije tvrdnja da Windows ne vidi kameru; E0173 je zasebno očitao PC Remote USB deskriptore.

Zato nema live popisa vlasnika ili proc stanja. Postojeći `native_freeze.h` odnosi se samo na PID149 i sam po sebi ne dokazuje pokrivenost svih vlasnika gadgetcore uređaja. Ne smije se upotrijebiti kao univerzalna potvrda da su svi stari ioctl pozivi završeni.

## Sljedeći integracijski uvjet

Sigurno postavljanje treba obuhvatiti stvarne vlasnike uređaja, već započete VFS ulaze, životni vijek wrappera i neovisne gadget/EP0 callbackove. Inventar je pripremljen za read-only dio tog postupka, a MOD gate/omotač E0174/E0175 ostaju izvan produkcijskog modula. Nije postavljen nesiguran pointer swap niti proglašena spremnost za aktivaciju. E0164 ostaje neučitan i `physical_test_ready:false`.
