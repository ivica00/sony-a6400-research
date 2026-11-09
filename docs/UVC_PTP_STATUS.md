# UVC + PTP: objedinjeni status i nastavak rada

**E0226 — spremljeni izlaz potvrđen:** [Fizička provjera](evidence/0226-preserved-monitor-output-acknowledgement.md) prvo je fsyncala/readbackom provjerila30115bajtova na hostu, zatim pomaknula samo izlazni RAM read pokazivač. Pogrešna potvrda je odbijena; ispravna ostavlja izlaz prazan i ulaz0/0. Osam ARM provjera prolazi. Naredbe nisu slane, SD nije pisan, kamera MSC/TracerPid0. Protokol nije multi-consumer CAS; sljedeće je ograničena nenapisna naredba uz očuvanje i prikupljanje rezultata.

**E0225 — izlaz monitora sigurno kopiran:** [Read-only čitač i fizički rezultat](evidence/0225-physical-readonly-monitor-output-capture.md) spremili su30115bajtova postojećeg izlaza uz jednake pokazivače prije/poslije. Red nije potrošen, naredbe nisu slane. Prolazi617testova. Čitač još ovisi o USB-u; stari spremljeni izlaz nije budući restart-otporan journal. Sljedeće su kontrolirano pražnjenje, provjera vlasništva i nenapisna probna naredba prije SD zapisa.

**E0224 — postojeći monitor kanal pronađen:** [Izvorni put i fizičko očitanje](evidence/0224-existing-monitor-transport-and-ring-contract.md) potvrđuju dijeljene RAM redove i izvršavanje naredbi u radnoj dretvi procesa. Devet originalnih ring slučajeva prolazi. Nije poslana nijedna naredba niti promijenjena memorija. Wrapperov povrat1 nije rezultat operacije, a izlaz može čekati pražnjenje; sljedeće je ograničeni čitač izlaza i provjera vlasništva prije nenapisne probne naredbe. SD još nije pisan.

**E0223 — ulaz za journal još se provjerava:** [Izvorni servisi](evidence/0223-journal-service-entry-and-creation-boundaries.md) pokazuju da IFSYS testne write naredbe mogu otvoriti postojeću datoteku i pišu numerički uzorak; nisu izvršene. Async API koristi privatni pthread red i može čekati bez roka. Dispatcher filesystem dretve nije opći write RPC. Windows E: trenutačno nije izložen. SD nije pisan; sljedeće je provjera izvornog monitor ulaza i vlasništva, uz postojeće odobrenje za mali journal.

**E0222 — SD put fizički identificiran:** [Ponovljeni read-only pokus](evidence/0222-physical-sd-volume-device-association.md) povezuje A: s `/dev/mmca` (SD/MMC250:10), a B: s `/dev/nflasha23` (interna flash252:23). Za journal se smije koristiti samo potvrđeni SD volumen; B: nije cilj. Obični PC Remote ciklus prošao je uredno, RAM datoteke očišćene, kamera MSC/TracerPid0/bez UVC modula. SD još nije pisan; slijedi stvaranje vlastite datoteke kroz postojeći native servis, uz provjeru bez prepisivanja i readback.

**E0221 — fizički pronađeni volumeni u PC Remoteu:** [60-sekundno promatranje](evidence/0221-physical-native-volumes-in-pcremote.md) bez zaustavljanja procesa pokazuje A: i B: nakon običnog prijelaza iz MSC-a. Potvrđene su stvarne GOT adrese tablica. Još nije identificirano koji je fizička SD kartica. Observer je završio, vlastite RAM datoteke uklonjene, kamera MSC/TracerPid0/bez UVC modula. SD još nije pisan; sljedeće je povezivanje volumena s medijem prije journal testa.

**E0220 — ugovor SD file API-ja:** [Izvorni kod i živa tablica](evidence/0220-native-filesystem-contracts-and-live-volume-table.md) potvrđuju status+izlazni handle za Open, create bez O_EXCL jamstva i lookup koji zadržava bravu. Devet Thumb guard slučajeva prolazi. U MSC je servis inicijaliziran, ali svih26slovnih volumena je prazno; nakon očitanja TracerPid0. SD još nije pisan. Slijedi identifikacija registriranog volumena/vlasnika u PC Remote/shooting načinu i provjera trajnog zapisa.

**E0219 — odobren trajni SD zapis:** [Preflight i sljedeći korak](evidence/0219-sd-journal-authorization-and-storage-preflight.md). Korisnik je odabrao mali dijagnostički zapis na SD-u. Obični PC Remote ciklus bez UVC-a uredno je prošao; u snimci Linux mountova nema SD filesystema, iako je mmca10p1 prisutan. Mrežni dijagnostički kanal nije dostupan. Pronađeni su izvorni Fsys API kandidati; njihov ABI i vlasništvo treba potvrditi prije prvog upisa. SD još nije pisan, kamera MSC, modul nije učitan.

**E0218 — DWC naredba ima brojač:** [Sedam ARM slučajeva](evidence/0218-original-endpoint-command-polling-and-stop-timeout.md) potvrđuje500provjera busy bita i povrat-110 ako se ne očisti. Izvorni STOP wrapper ipak briše resursne oznake i nakon tog timeouta; one nisu dokaz zaustavljenog DMA-a. Stvarno trajanje i hardverski ishod nisu izmjereni. Pullup čekanje ostaje druga, neograničena putanja. Kamera nije dirana.

**E0217 — USB red i DWC dequeue:** [Deset novih slučajeva](evidence/0217-original-event-producer-and-dwc-dequeue.md) izvršava izvorni proizvođač događaja i DWC otkazivanje. Pun red vraća pogrešku; neregistrirani kontekst može vratiti 0 bez događaja. DWC completion ide nakon otpuštanja brave, a aktivni zahtjev prvo ulazi u hardverski STOP koji još nije izvršen u pokusu. Stvarne brave/MMIO i uzrok zamrzavanja ostaju otvoreni. Kamera nije dirana.

**E0216 — STOP i sinkroni completion:** [Četiri nova slučaja](evidence/0216-ptp-stop-synchronous-read-completion-locks.md) izvršavaju izvorni PTP lanac kroz otkazivanje OUT zahtjeva i read completion. U tom scenariju dequeue otpušta +0x2a0 prije completiona; completion ne uzima već držanu STOP bravu +0x258. To sužava sumnju na izravno samoblokiranje u tom putu, uz izričite servisne zamjene; nije dokaz odsutnosti drugih zastoja. Kamera nije dirana.

**E0215 — runner provjerava gašenje:** [Promjena i provjere](evidence/0215-runner-stop-receipt-before-retirement.md). Nakon svakog pokušaja INIT-a traži uspješan STOP i potpuno prazan status sesije prije povlačenja ulaznog hooka. Pri pogrešci zadržava FD i pokušava spremiti zapis; ne ponavlja cleanup niti zatvara uređaj. Osam ARM scenarija i 612 testova prolazi. Nije postavljen na kameru; već blokiran kernel poziv ovime nije riješen. Preostaju neovisni dohvat dijagnostike i analiza callback/brava.

**E0214 — stvarni PTP STOP:** [Izvorni modul i pokus](evidence/0214-original-ptp-stop-and-event-adapter.md) potvrđuju redoslijed mutex/dequeue/oslobađanje/status/obavijest. Dva ARM slučaja izvršavaju STOP i adapter događaja; u njihovu tijelu nema izravnog čekanja aplikacijske potvrde nakon predaje u red. Stvarne brave, dovršeci i red još su servisne granice; uzrok zastoja nije dokazan. Kamera nije dirana.

**E0213 — redoslijed STOP-a:** [Izvorni ARM kod](evidence/0213-original-interface-stop-ownership-order.md) u četiri slučaja potvrđuje da se oznaka aktivnog drivera briše prije STOP callbacka; endpointi se oslobađaju nakon njegova povratka. Sama neaktivna oznaka zato nije dokaz dovršenog gašenja ili dopuštenje za ponavljanje cleanup-a. Stvarni callback i mjesto zastoja još nisu dokazani; ovaj korak nije pristupao kameri.

**E0212 — OBS je pokušao otvoriti kameru:** [Zapis i granica UVC kontrola](evidence/0212-obs-video-open-and-enumeration-control-boundary.md). Lokalni OBS log potvrđuje ILCE-6400/MI_01, MJPEG720p30 tijekom E0210. To ne dokazuje uzrok zamrzavanja; ConnectPins prekid slijedi gašenje OBS-a. Kandidat je ranije blokirao START, ali prosljeđivao UVC kontrolne zahtjeve. Novi enumeration-only način izričito odbija CLASS/VENDOR zahtjeve; 12 ARM slučajeva, 118 provjera modula i 612 testova prolazi. Nije postavljen na kameru. OBS ostaje zatvoren za budući baseline, uz nastavak analize zaustavljanja i dohvata dijagnostike.

**E0211 — offline analiza zaustavljanja:** [Provjera izvornog puta](evidence/0211-configured-session-teardown-boundary.md) potvrđuje da konfiguracija 0 preskače gašenje sučelja, a konfiguracija 1 prolazi njihove STOP pozive. Stari uspješni testovi zato ne dokazuju pouzdanost novog konfiguriranog puta. Dodana je dijagnostika koraka bez promjene redoslijeda; četiri nova ARM slučaja i 118 provjera kandidata prolaze. Kandidat nije postavljen na kameru. Prije sljedeće aktivacije ostaju stvarni callback ugovori, dohvat zapisa pri zastoju i obrada neuspjelog STOP-a u runneru.

**E0210 kamera oporavljena:** korisnikov ponovni start vratio je izbornik i MSC. Očitavanje potvrđuje debugger703, TracerPid0 i odsutnost modula usbg_video. Skup naziva modula odgovara početnom, ali to nije potvrda urednog povlačenja tijekom testa. Točno mjesto zastoja ostaje nepoznato jer završni zapis nije dohvaćen prije ponovnog starta. Sljedeće je pouzdano zaustavljanje konfigurirane sesije prije novih aktivacija.

**E0210 oporavak:** nakon uspješne enumeracije izbornik kamere se zamrznuo; odspajanje USB-a nije pomoglo. Završni zapis, povlačenje hooka i uklanjanje modula nisu potvrđeni. Korisniku je zadan ponovni start bez USB-a i povrat u MSC. Prije novog fizičkog testa obvezno potvrditi oporavak i istražiti zaustavljanje već konfigurirane sesije. Protek vremena host nadzora nije dokaz STOP uspjeha.

**E0210 — oba Windows poduređaja prepoznata:** [Izvorni sukob endpointa i ispravak](evidence/0210-original-endpoint-number-conflict.md). Sonyjev SET_CONFIGURATION skenira broj endpointa bez smjera; PTP OUT02 i UVC IN82 na različitim sučeljima sukobljavaju se. Kandidat premješta UVC na IN84 uz usklađen deskriptor, odabir endpointa i START tag. Fizički test potvrđuje roditelja usbccgp, PTP MI_00/WUDFWpdMtp i kameru MI_01/usbvideo istodobno Status OK, Code0. Video je i dalje isključen, upravljačke transakcije nisu provjerene. Završno očitanje/čišćenje čeka povrat kamere u MSC; ne pretpostaviti da je modul uklonjen. 118 ARM provjera modula, 155 životnog ciklusa i 612 testova prolazi.

**Najnoviji fizički nalaz E0209:** [Dijagnostički 90-sekundni test](evidence/0209-physical-control-trace-unconfigured-composite.md) ponovno pokazuje roditeljski Code 10 (`0xc0000001`), bez djece. Kamera vraća deskriptore, ali uzorkovana USB konfiguracija ostaje 0; nema zapisa native ioctl poziva tijekom sesije. Uzrok još nije dokazan. INIT/STOP/povlačenje hooka i automatsko čišćenje uspješni; kamera MSC, modul uklonjen, popis modula obnovljen. 118 ARM provjera i 612 testova prolazi. Sljedeće: provjera deskriptora i odabira konfiguracije; senzorski video još nije uključen.

**Noviji nalaz E0208 — 9. studenoga 2026.:** [90-sekundni test](evidence/0208-windows-90s-parent-code10-and-feeder-boundary.md) potvrdio je urednu kamerinu aktivaciju/STOP/retirement, ali Windowsov kompozitni roditelj s već vezanim `usbccgp` ostaje na **Code 10**, bez `MI_00`/`MI_01`. Dulje čekanje nije riješilo pokretanje roditelja. Kamera je vraćena u MSC, modul uklonjen, početni popis modula potpuno vraćen. Sljedeće je dijagnostika roditelja/kontrolnih zahtjeva; ne forsirati child drivere dok djeca ne postoje. Host alat sada razlikuje roditelja od PTP djeteta; 612 testova prolazi. Offline zaštita od preklapanja JPEG izvora i DMA odredišta je dodana, ali senzorski feeder još nije povezan niti pokrenut.

**Presjek: 8. studenoga 2026., do E0207.** Ovo je početna točka za nastavak UVC/PTP rada. Detaljni izvori, ograničenja i fizički zapisi nalaze se u povezanim dokazima.

## Cilj i trenutačna granica

Cilj je da Windows prepoznaje a6400 kao UVC kameru, uz istodobno Sony PTP/PC Remote upravljanje iz naših budućih programa. Sonyjevi programi nisu uvjet. Želimo stvarni senzorski video, uz očuvane izvorne odluke i ponašanje kamere.

**Faza 3 (Prva kompozitna USB enumeracija u PC Remote načinu rada) uspješno je fizički postignuta na živoj kameri (E0207).**
Usklađivanjem 56-bajtne `struct uvc_user_probe_info` ABI strukture i uvođenjem nebaferiranog zapisivanja, session runner na kameri je preživio prelazak u PC Remote način rada, dinamički detektirao `054C:0CAA`, zamrznuo 181 dretvu PID-a 149 na 1.452 ms, postavio hook na `0x602b8844` uz 4-jezgrenu sinkronizaciju predmemorije, uspješno izvršio `IOCTL_UVC_INIT` (`ret=0`) i aktivirao kompozitnu sesiju. Windows PnP je na sabirnici odmah prepoznao i zabilježio uređaj kao **`USB Composite Device (USB\VID_054C&PID_0CAA\CF93603BE631)`**. Nakon 30 sekundi sesija je uredno zaustavljena, hook povučen uz vraćanje originalne instrukcije `0xe1a0c00d`, modul uklonjen, a `/proc/modules` vraćen bajt-po-bajt identičan početnom stanju.

| Rezultat | Što dokazuje | Što još ne dokazuje |
| --- | --- | --- |
| [E0143](evidence/0143-uvc-720p-test-transport-and-30fps-verified.md), E0150 | Sony UVC prijenos statičnog uzorka 1280×720 približno 30 FPS | Senzorski UVC ili istodobne kontrole |
| [E0151](evidence/0151-pc-remote-liveview-and-uvc-verified.md) | Stvarni senzorski JPEG preko PTP-a u PC Remoteu, 1024×680 | Prijenos tog senzora kroz UVC |
| [E0205](evidence/0205-physical-entry-hook-lifecycle-verified.md) | Sigurno postavljanje/povlačenje native hooka pod stop scopeom na 4 jezgre | Aktivaciju zajedničke USB sesije |
| [E0207](evidence/0207-first-physical-composite-pcremote-enumeration.md) | **Prva fizička kompozitna enumeracija u PC Remoteu (`054C:0CAA`) kao `USB Composite Device` uz čist povratak** | Stalnu instalaciju Windows drivera na djecu kompozita i senzorski feeder |

## Posljednje zabilježeno stanje kamere

- Kamera je vraćena u **Mass Storage**. Debugger PID 791 odgovara.
- Sonyjev `im.elf` je PID 149; pre/post provjere nalaze identičan skup od **181 dretve**, `TracerPid=0`, bez rušenja ili kernel grešaka.
- Modul kandidat E0206 je testiran, zatvoren i uklonjen; `/proc/modules` vraćen je bajt-jednak na stanje prije testa (41 modul).
- Privremeni runner i modul s flash particije `/setting` i `/tmp_bt` su u potpunosti uklonjeni; memorija i resursi su vraćeni.
- Svi emulator testovi (605/605) prolaze u 15.605s.

## Što je implementirano i provjereno

| Područje | Stanje i dokaz |
| --- | --- |
| Native/MOD zaštita | Atomska zaštita razlikuje izvorne pozive i MOD rezervaciju. Rezervacija ostaje kroz ACTIVE/HELD sesiju; INIT odbija nepovezani native ulaz. [E0182](evidence/0182-session-lifetime-native-exclusion-and-route-precondition.md) |
| USB završavanje zahtjeva | Izvorni ARM kod ispitan za busy oznaku, redoslijed isključivanja, EP0 prihvat i završne pozive. Offline ugovori sa servisnim fixtureima. [E0184](evidence/0184-original-dwc-pullup-drain-order.md) – [E0189](evidence/0189-public-ep0-queue-lock-and-admission.md) |
| Oporavak CPU zaustavljanja | Stvarni helper pamti uspješno/neuspješno odvojene dretve, ne gubi vlasništvo nakon djelomičnog neuspjeha i može izgraditi novu barijeru. [E0192](evidence/0192-retry-safe-native-cpu-barrier.md) – [E0195](evidence/0195-physical-stop-signals-and-original-signal-entry.md) |
| Kernel provjera dretvi | Native `ptrace`, procfs pripadnost PID/TGID, broj dretvi, glavna dretva, korisnički način i SIGSTOP. Na kameri 174/181 prolazi. [E0197](evidence/0197-physical-native-stop-diagnostic-verified.md), [E0198](evidence/0198-kernel-thread-membership-physically-verified.md) |
| Opseg u kernel memoriji | Registarske/siginfo snimke i kopija TID-ova ostaju u kernelu. Interni potrošač izvršava se sinkrono prije povratka; nema trajnog korisničkog tokena. [E0199](evidence/0199-kernel-owned-snapshots-and-synchronous-scope.md) |
| Životni vijek zaštite | Publish/retire/recover politika zadržava modul pri neuspjehu. Cijeli ciklus s pravim module-get/put provjeren na vlastitoj testnoj riječi. [E0200](evidence/0200-integrated-private-route-lifetime-cycle.md) |
| Ulazni most | Offline most obuhvaća i ranije učitan VFS pokazivač, čuva izvorni okvir stoga i nastavlja izvorni ioctl bez rekurzije. [E0201](evidence/0201-original-native-entry-bridge-and-cached-vfs-target.md) |
| Više jezgri i cache | Izvorni redoslijed potvrda ispitan offline. Novi cache postupak fizički provjeren na testnoj riječi: oba prolaza `seen=f expected=f result=0`, sve četiri jezgre. [E0202](evidence/0202-original-smp-callback-completion.md), [E0203](evidence/0203-four-core-code-visibility-physically-verified.md) |
| Ulazni most, drain i backend flush | Povezan E0201 most u modul uz ugovor pražnjenja poziva i četverojezgrenu sinkronizaciju predmemorije. [E0204](evidence/0204-entry-bridge-caller-drain-and-descriptor-flush.md) |
| Fizički ulazni hook i sinkronizacija | Fizički provjereno postavljanje branch instrukcije na 0x602b8844, četverojezgrena sinkronizacija cachea, vraćanje izvornog `mov ip,sp`, samostalno pinanje i odpinavanje (1418 ms) bez rušenja. [E0205](evidence/0205-physical-entry-hook-lifecycle-verified.md) |
| **Prva kompozitna enumeracija u PC Remoteu** | **Ispravljen 56-bajtni ABI deskriptora; runner preživio warmboot, postavio hook na 181 dretvu, aktivirao `IOCTL_UVC_INIT` (ret=0); Windows prepoznao kameru kao `USB Composite Device (054C:0CAA)`; 30s sesija uspješno zaustavljena i povučena bez ikakvih nuspojava.** [E0207](evidence/0207-first-physical-composite-pcremote-enumeration.md) |

## Posljednji kandidat i provjere

- Modul: [usbg_video_a6400_shared_candidate.ko](../artifacts/native/uvc-ptp-module-e0206/usbg_video_a6400_shared_candidate.ko), **70.996 bajtova**, SHA-256: `7adc42e6e981270860e4c383368d2df87a3851aa775f150792610d320aa49a6e`
- Runner: [uvc_ptp_session_runner.elf](../artifacts/native/uvc-ptp-runner-e0206/uvc_ptp_session_runner.elf), **11.532 bajtova**, SHA-256: `5afb579491907b0aa7e4ae3db1b09acd170b5207635b326e1e86b92d2850463d`
- **605 projektnih testova** prolazi u **15,605 s**.

## Što slijedi

1. **Usklađivanje Windows Host drajvera za kompozitne pod-uređaje (`usbccgp.sys`)**:
   Budući da Windows veže `wpdmtp.inf` na `054C:0CAA` kada je kamera ne-kompozitna, pri kompozitnoj enumeraciji Windows učitava Generic Parent Driver (`usbccgp.sys`), koji stvara dva djeteta:
   - `USB\VID_054C&PID_0CAA&MI_00` (PTP / WPD)
   - `USB\VID_054C&PID_0CAA&MI_01` (UVC Video)
   Potrebno je osigurati trajanje sesije (npr. 60–120 s) i/ili pridružiti odgovarajući `.inf` kako bi Windows završio instalaciju oba drajvera.
2. **Povezivanje senzorskog video feedera s koherentnim DMA bufferima**:
   Povezati provjereni senzorski JPEG izvor (Scalar/ISP) s video streaming endpointom `0x82` kako bi kompozitni UVC stream u stvarnom vremenu prikazivao živu sliku sa senzora.
