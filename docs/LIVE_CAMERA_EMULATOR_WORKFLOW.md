# Workflow: živa kamera i izvršavanje izvornog koda u emulatoru

Ovaj postupak koristi fizičku ILCE-6400 kao izvor opaženog stanja, a emulator
kao mjesto za ponovljivo izvršavanje i provjeru izvornih instrukcija. Cilj je
otkriti stvarne ugovore firmwarea i hardvera. Broj izvršenih instrukcija ili
uspješan izolirani poziv ne dokazuju funkcionalnost cijele kamere.

## Podjela poslova

| Živa kamera | Emulator |
| --- | --- |
| Stvarni widgeti, modeli, registri, događaji i kontekst dretve | Izvršavanje originalnih ARM/Thumb instrukcija nad sačuvanim stanjem |
| Provjera učitanih modula i njihovih stvarnih adresa | Praćenje čitanja, pisanja, poziva i granice na kojoj nedostaje ugovor |
| Kratki, unaprijed pripremljeni pokusi korisnika u meniju | Ponavljanje, rubni slučajevi, nevažeći indeksi i usporedba rezultata |
| Završna provjera ponašanja na fizičkom uređaju | Priprema provjerljivog kandidata prije fizičke promjene |

USB način rada mijenja aplikacijsko stanje: meni može nestati iz aktivnog
stabla. Zato negativan USB scan nije dokaz da widget ne postoji u MENU načinu.
Kasniji USB snimak modela može odgovarati poljima menija, ali se time ne dobiva
atomski snimak niti jamstvo da su svi ostali podaci ostali isti.

## Priprema i pristup

1. Pročitati najnoviji zapis na vrhu [AGENTS.MD](../AGENTS.MD), zatim navedene
   evidence dokumente. Starije upute o čekanju pokusa mogu biti nadjačane novijim
   završenim snimkom. Ne pokretati starog promatrača samo zato što postoji.
2. Koristiti instalirani [native USB debugger](NATIVE_USB_DEBUGGER.md) u normalnom
   MSC načinu, preko `tools/camera_debugger.py`. Ne ponavljati Senser bootstrap
   za rutinsko očitanje. Koristiti postojeći host Python s potrebnim USB/Crypto
   paketima; ne pretpostavljati da ih sadrži venv.
3. Utvrditi PID, mapiranje modula, verziju i identitet izvora. Za svaku funkciju
   razlikovati ELF adresu, runtime adresu, pomak unutar modula i Thumb bit.
4. Pripremiti usko pitanje: npr. koji objekt vraća lookup, koji model pripada
   redu, koja se polja mijenjaju ili gdje se pojavljuje nepodržan poziv.

Rutinske naredbe su čitanje, ne ulazak u servisni način:

```powershell
python tools/camera_debugger.py info
python tools/camera_debugger.py maps 149
python tools/camera_debugger.py threads 149
```

Debuggerovo očitanje memorije privremeno zaustavlja odabranu dretvu. Ne zamrzava
sve dretve procesa i ne proizvodi atomski snimak. Sesije su zaključane na hostu;
ne koristiti istodobno konkurentne klijente za kameru.

## Osnovni ciklus istraživanja

1. **Izvor i identitet.** Očitati samo potrebne prozore koda/podataka. Kod
   usporediti s odgovarajućim ELF-om na kameri. Ako se razlikuje, sačuvati obje
   verzije i razlike; ne ukloniti provjeru. Učitane relokacijske tablice i
   runtime kernel helperi zahtijevaju odvojenu kvalifikaciju, ne lažnu tvrdnju
   da su jednaki sirovoj datoteci.
2. **Stvarno stanje.** Sačuvati objekt, vtable, polja i potrebne rubove grafa.
   Provjeriti tip, self-pointer, granice i cikluse. Za modele sačuvati stvarne
   nizove djece; ne popunjavati nedostajuće susjede nulama. Ponovno očitanje
   roditelja može otkriti promjenu tijekom čitanja, ali ne dokazuje atomskost.
3. **Izvorno izvršavanje.** U emulator mapirati samo opažene bajtove i provjeren
   kod. Postaviti ABI, stack, povratnu adresu i arhitekturno stanje. Za VFP
   uključiti odgovarajuće registre; za pthread put potrebni su stvarni TLS i
   identitet dretve. Konstruirane ulaze izričito označiti kao kontrolne pokuse.
4. **Stroge granice.** Zaustaviti se na nepoznatom kodu, neopaženom čitanju,
   sukobu snimaka, nepodržanom sistemskom pozivu ili neprovjerenom pisanju.
   Sačuvati PC, registre, trace i dotadašnja pisanja. Nedostajući odgovor nije
   dozvola da host vrati očekivani uspjeh.
5. **Ciljano dopunjavanje.** Sljedeće očitanje određuje konkretna granica iz
   emulatora. Očitati odgovarajući kod ili mali prozor podataka i ponoviti od
   početnog stanja. Za pisanje prvo dokazati ugovor: polje, širinu, izvornu
   instrukciju i očekivane nuspojave. Promjene u kopiji emulatora nisu dozvola
   za istu promjenu na kameri.
6. **Kontrole.** Usporediti rezultat s opaženim stanjem. Dodati smislene rubne
   slučajeve: isti odabir bez promjene, nevažeći indeks bez pisanja, lijevi/gornji
   i desni/donji rub, drugi redoslijed izvršavanja u svježem emulatoru. Ponoviti
   prethodne provjere kad zajednički kod bude promijenjen.
7. **Zaključak.** Odvojiti opažanje na kameri, statički dokaz, izvršavanje
   izvorne funkcije, konstruirani pokus i još neprovjerenu fizičku funkciju.
   Zapisati što je sljedeća granica i je li fizički pokus stvarno potreban.

## Kada treba pokus korisnika na kameri

Promatrača prvo izgraditi, učitati, usporediti read-back i provjeriti da stvarno
čeka pravi MENU objekt. Koristiti ograničeno trajanje, broj pokušaja, veličinu
izlaza i zaseban stop-marker. Prednost ima okidanje stvarnim widgetom nad fiksnim
odgađanjem. Tek tada tražiti kratku i jasnu sekvencu korisnika: odspajanje USB-a
bez gašenja, MENU, potrebni pritisci ili kotačić s razmacima, ponovno spajanje.

Nakon povratka **najprije sačuvati sve privremene zapise**, uključujući binarnu
datoteku i tekstualni status, pa tek onda zaustavljati ili čistiti vlastite alate.
Provjeriti završni marker, rezultat, broj zapisa, točnu duljinu i hash. Zapis bez
END ili s odrezanim zadnjim objektom ostaje izričito djelomičan; ne nadopunjavati
nedostajuće bajtove. `/tmp_bt` je u ovom istraživanju tmpfs od samo 1 MiB.

Stare vlastite logove brisati tek nakon provjere jednakosti s potpunom lokalnom
arhivom. Ne brisati nepovezane datoteke. Fizička SD kartica za emulator ostaje
read-only; autorizacija za SD modifikacije kamere opisana je u AGENTS.MD.

## Primjeri koje smo ovim ciklusom dokazali

| Korak | Dokaz i ograničenje |
| --- | --- |
| Aktivni lookup menija | E0106: originalni ugniježđeni lookup vraća stvarni ListTab u 795 instrukcija; host ne podmeće zasebno pronađen objekt |
| Geometrija | E0106: 145 widgeta; svježe izvršavanje obrnutim redoslijedom daje iste koordinate; posebna uska kvalifikacija Unicorn IT stanja |
| Model i redovi | E0107: sva polja bindinga se podudaraju; šest originalnih indexed lookup poziva povezano je sa statički dokazanim rasporedom redova |
| Područje pogotka | E0108: 252 originalne `isHit` provjere; zasebne originalne selection kontrole; to još nije fizičko input usmjeravanje |
| TLS i aktivacija | E0109: bez TLS-a pogrešna visoka adresa; s očitanim main-thread kontekstom i stvarnim kernel kodom prolazi zaključavanje; zaustavljanje prije neprovjerenog resource-manager pisanja |

Primjeri ponovljivih lokalnih provjera, uz prethodno sačuvane privatne ulaze:

```powershell
python -m tools.research.active_menu_snapshot_probe
python -m tools.research.menu_binding_snapshot_probe --active-layout
python -m tools.research.menu_row_snapshot_probe
python -m tools.research.menu_row_hit_snapshot_probe
python -m tools.research.menu_activation_snapshot_probe
python -m tools.research.menu_activation_snapshot_probe --main-thread-control
python -m unittest discover -s tests -q
```

`capture_menu_activation_dependencies` kontaktira kameru; nije samo offline
provjera. Pozivi se ograničavaju s `--steps`, a main-thread kontrola označava se
zasebnim argumentom. Ne proširivati listu dopuštenih pisanja samo da bi poziv
završio. Glavna dretva nije automatski dokazana izvorna UI dretva.

## Što čuvati i što objaviti

U `docs/evidence/` zapisati identitet ulaza, naredbe, pokus, rezultate, odstupanja,
preostalu granicu i stanje promatrača. Na vrhu AGENTS.MD ostaviti kratke upute
za nastavak; ažurirati README, roadmap i trenutni status bez prepisivanja starih
neuspjelih pokusa kao uspjeha.

U Git idu izvorni alati, testovi, dokumentacija i sažeti metapodaci. Firmware,
proprietarni ELF-ovi, sirova memorija, SD sadržaj, checkpointi i veliki generirani
artefakti ostaju u privatnoj lokalnoj arhivi prema `.gitignore`. Putanja do
artefakta u dokumentu ne znači da je njegov sadržaj javno dostupan ili da svježi
clone sam može reproducirati pokus bez potrebnih vlastitih ulaza.
