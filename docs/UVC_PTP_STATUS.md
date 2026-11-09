# UVC + PTP: objedinjeni status i nastavak rada

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
