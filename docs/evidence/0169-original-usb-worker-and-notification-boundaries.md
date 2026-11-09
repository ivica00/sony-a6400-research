# E0169 — Izvorna glavna petlja i put završne obavijesti

Datum: 2026-11-08. Offline nastavak E0168; bez pristupa kameri i bez izmjene produkcijskog C modula.

`tools/research/probe_uvc_ptp_worker.py` izvršava izvorni Thumb entry 0x10175, `UsbControl::Main` 0x112c5, `ProcessMsg` 0x10ed5, prefix registracije povratnog poziva, tijelo registriranog callbacka do buildera poruke i `EventListner` do predaje UFW servisu. Izvor: a6400 libUsbControl.so SHA-256 `70cd5742fde9eea78c60905e4015531b4c3ab2668d2cb85c934531f451f1211f`.

## Glavna petlja

Originalni entry poziva Init i zatim Main s istim objektom. Originalni Main koristi MsgReceiver na this+0x70, prima izvor i ObjMsg te sinkrono poziva ProcessMsg. Nakon povratka uništava i briše poruku prije sljedećeg receive. ProcessMsg na fixture kategoriji 0x6103 i message ID-u 0xa2000 zove SetCmpTarget i DispatchEvent, a zatim vraća 0. Exit ID 0xffff0000 vraća -1, uz završno čišćenje poruke i izlazak iz Main.

Pokus izvršava dvije uzastopne poruke te exit. Provjerava redoslijed receive → target → dispatch → destructor → delete prije sljedećeg receive. Izvorne odluke Main/ProcessMsg nisu zamijenjene. Receive, ObjMsg getters, Init, SetCmpTarget, DispatchEvent, destructor i delete su izričite servisne zamjene. FSM callbackovi nisu izvršeni; ovo nije dokaz da sve promjene konfiguracije fizički dolaze kroz jednu jedinu dretvu.

## Registracija i obavijest

Originalni doInitialize prefix 0x131c1..0x131d8 predaje osal_reg_msg_queue_cb argumente:

| Argument | Vrijednost u originalnom kodu/fixtureu |
|---|---|
| r0 | 0x00e942cd |
| r1 | wrapper+0x20 |
| r2 | originalni Thumb callback 0x131a5 |
| r3 | 0 |

Zaustavlja se prije preostale inicijalizacije. Stvarno registriranje, tumačenje svih OSAL argumenata i dretva callbacka nisu dokazani.

Originalni callback 0x131a5 učitava prva dva worda primljene poruke i prosljeđuje ih builderu na 0x13055. Na eksplicitnoj poruci `{1, -5}` provjereni su r0=1 i r1=-5 na granici prije buildera. Builder nije izvršen u ovom pokusu, pa nisu dokazani ObjMsg konstrukcija, uspješno slanje ni oslobađanje ulazne poruke.

Zasebno, originalni `UsbIfWrapper::EventListner` 0x12d29 prilagodi this na wrapper+8 i predaje isti ObjMsg u `UFW::MsgSender::SendEvt` preko Thumb PLT ulaza 0x9808. Na toj granici pokus staje: uspješno slanje, ciljni red i isporuka nisu pretpostavljeni.

Ovaj registrirani OSAL notification callback **nije isto** što i izravni USB completion callback 0x12de5 iz E0168. Prvi put stvara obavijest za aplikaciju; drugi šalje status u privremeni red na kojem doSyncStartStop čeka. Njihova točna raspodjela po dretvama još nije izvršno potvrđena.

## Resolver i provjere

`arm_plt.py` sada prepoznaje i točan Thumb interworking prefix `bx pc; mov r8,r8` (bajtovi 78 47 c0 46) te povezuje njegov ulaz s dokazanim ARM stubom i ELF relokacijom. Time ispravno razrješava tail pozive koji prije nisu imali rezultat, bez nagađanja razmaka.

**18 novih provjera prolazi**; manifest je `artifacts/analysis/uvc-ptp-worker-e0169/manifest.json`, zapis `artifacts/uvc-ptp-worker-e0169.log`. Nakon promjene resolvera ponovno prolaze i 22 completion provjere E0168 te 35 provjera reda E0166. Fizički pristup nije korišten. Zadnja puna projektna regresija ostaje 605 prolaznih testova E0164; produkcijski modul nije promijenjen.

## Sljedeća granica

Pratiti izvorni OSAL callback dispatcher za osal_reg_msg_queue_cb i njegov odnos prema USB completion pozivatelju. Za zaštitu transakcije trebaju provjerljivi identiteti izvršitelja i trajanje callbacka, a ne zaključak da je svaka obavijest automatski serijalizirana glavnom petljom. Zajednički modul ostaje neučitan i fizički nepodvrgnut provjeri; istodobni senzorski UVC i PTP ostaju nedovršeni.
