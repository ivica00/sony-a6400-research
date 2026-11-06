# Plan poboljšanja emulatora za GUI, Meni i Touch modove

> Status 2026-11-06: plan ispod je povijesni radni dokument. Stvarni glavni
> meni je PAS_MenuListTab, a ne ranije pretpostavljeni PAS_MenuSelectMode.
> MonDrv red stvoren pri obnovi checkpointa nije dokazana izvorna inicijalizacija
> i ostaje otvorena nepravilnost. UIPC granica veličine odnosi se na određeni
> provjereni poziv, ne na univerzalno pravilo za svaku poruku. Aktualne rezultate
> i ograničenja donose E0106–E0109; touch glavnog menija još ne radi.

## 1. Cilj i kontekst
Cilj je unaprijediti emulator Sony ILCE-6400 kamere do točke gdje se firmware moduli zaduženi za grafičko sučelje (`libObj.so`, `viewUnified2.so`), hijerarhiju izbornika (`PAS_MenuSelectMode`, `GEN_GridList`) i unos dodirom (`ux::wgtsys::WidgetSystem`, `InputService`, `InfraTp`) mogu autentično izvršavati i testirati unutar emulatora bez potrebe za neposrednim flashanjem/testiranjem na fizičkoj kameri.

Svi ugovori i mehanizmi temelje se na matematički i telemetrijski verificiranom stanju stvarne kamere (Sony ILCE-6400, FW 2.00, Serijski br. 03925553) spojenoj putem Native Root USB Debuggera (`docs/NATIVE_USB_DEBUGGER.md`).

---

## 2. Arhitektonska analiza i otkriveni ugovori

### 2.1. Autentični 12-bajtni OSAL UIPC zaglavlje (`osal_uipc.ko` / `libosal_uipc.so`)
- Korisnički `msg_ptr` kojeg vraća `osal_valloc_msg_wait` ima memorijsku strukturu:
  - `msg_ptr - 12` (`raw + 0`): link/pool descriptor (4 bajta)
  - `msg_ptr - 8` (`raw + 4`): `num_blocks` (1 bajt):
    - `0` ako je zatražena veličina `<= 20` bajtova (tada `osal_msg_size` vraća točno 20)
    - `((size + 43) & ~31) >> 5` ako je zatražena veličina `> 20` bajtova (tada `osal_msg_size` vraća `(num_blocks * 32) - 12`)
  - `msg_ptr - 7` (`raw + 5`): zastavice / status (1 bajt, inicijalno 1)
  - `msg_ptr - 6` (`raw + 6`): uint16 `ref_count` (2 bajta, inicijalno 1, atomski dekrementiran u `osal_free_msg`)
  - `msg_ptr - 4` (`raw + 8`): magična vrijednost / red pošiljatelja (`0xa5a5a5a5` ili queue ID)
  - `msg_ptr + 0` (`raw + 12`): korisnički payload pokazivač
- `libInfraMediaDetect.so` na adresi `0xcd10` eksplicitno provjerava:
  ```arm
  blx osal_msg_size
  cmp r0, #0x17
  bls error  ; ako je veličina <= 23 bajta, odbacuje poruku!
  ```
  Zato svaka UIPC poruka mora imati `num_blocks >= 2` (raw veličina >= 64 bajta).

### 2.2. Uzrok `SIGFPE` (division by zero) u `MonQueue::EnQueue` (`libMWF.so`)
- `THREAD_INFRA1` (TID 1004) prilikom inicijalizacije poziva `MonCtrl::ConPutMessage` -> `MonDrv::PutcharSub`.
- `MonDrv::PutcharSub` dereferencira `MonDrv::mp_output` (GOT offset `0xc88`).
- U emulatoru je `MonDrv::mp_output` bio NULL (`0x0`). Zbog `null_page_policy='read-zero'`, `MonQueue::IsFull(0)` je vratio 0 (nije pun), a zatim je `MonQueue::EnQueue(0, ch)` izvršio:
  ```arm
  ldr r1, [r3, #0xc]  ; r1 = capacity (čita [0 + 0xc] = 0)
  ldr r0, [r4]        ; r0 = write_idx (0)
  adds r0, #1
  blx __aeabi_uidivmod ; dijeli (write_idx + 1) / capacity -> 1 / 0!
  ```
  Dijeljenje s nulom podiglo je `SIGFPE` (signal 8) putem `sys_tgkill(1000, 1004, 8)`.
- Telemetrija s prave kamere (`camera_debugger.py` mem dump):
  - `MonDrv::mp_output` na živoj kameri pokazuje na validan objekt `0x000218e8`:
    - `read_idx_ptr = 0x0450e408`
    - `write_idx_ptr = 0x0450e40c`
    - `buf_ptr = 0x0450e810`
    - `capacity = 0x00007bf0` (31,728 bajtova)
  - Objekt je mapiran iz `/dev/mem` na fizičkoj adresi `0x20098000` (WBI log međuspremnik iz `backup.ko` stavki `0x00fa0028` i `0x00fa005d`).

---

## 3. Akcijski plan po fazama

### Faza 1: Učvršćivanje ugovora u jezgri emulatora
1. **Ažuriranje `GuestUipc` (`src/a6400/execution/guest_uipc.py`)**:
   - Implementirati autentični 12-bajtni OSAL format zaglavlja u `handle_valloc_msg_wait` i `allocate_message`.
   - Pohranjivati `num_blocks` na `raw + 4` (`msg_ptr - 8`), `ref_count = 1` na `raw + 6`, i marker `0xa5a5a5a5` na `raw + 8`.
   - Ažurirati `tests/test_guest_uipc.py` i osigurati prolaz svih unit testova.
2. **Inicijalizacija `MonDrv::mp_output` / WBI međuspremnika**:
   - Prilikom učitavanja ili pripreme emulatora, alocirati/povezati autentični `MonQueue` objekt kapaciteta `0x7bf0` s pokazivačem `MonDrv::mp_output` u `libMWF.so`.
   - Time se potpuno eliminira mogućnost rušenja logging podsustava (`SIGFPE`) tijekom boot sekvence bilo koje niti.

### Faza 2: Napredovanje niti do spoja (Join)
1. **Izvršavanje TID 1004 (`THREAD_INFRA1`) i TID 1039 (`IMD-RM`)**:
   - Omogućiti TID 1004 da obradi medijski odgovor i završi registraciju.
   - Povezati `THREAD_INFRA0` (TID 1001) sinkronizacijski cjevovod (`thread_1008` render signal na condvar `0x000284b0`).
2. **Spremanje stabilne međutočke**:
   - Kreirati checkpoint `artifacts/checkpoints/boot-infra-ready.ckpt`.

### Faza 3: Instanciranje `WidgetSystem` singletona i `viewUnified2.so`
1. **Napredovanje glavne niti (`im.elf`)**:
   - Nakon što infra niti signaliziraju spremnost, `main` nit nastavlja izvršavanje prema instanciranju GUI singletona.
   - Verifikacija postojanja `ux::wgtsys::WidgetSystem` na `libObj.so` adresi `0x07108058` -> `0x000956f0`.
   - Verifikacija tablice slojeva (8 slojeva) i stanja miša na `+0x4a8` / `+0x4b0`.
2. **Učitavanje stabla izbornika**:
   - Izvršavanje ulaznih točaka u `viewUnified2.so` (`PAS_MenuSelectMode`).
   - Kreiranje checkpointa `artifacts/checkpoints/boot-gui-ready.ckpt`.

### Faza 4: Injekcija dodirom (Touch Injection) i interaktivni testovi
1. **Modeliranje unosa dodirom**:
   - Povezivanje virtualnog touch sučelja s `WidgetSystem` poljima za koordinate i stanje pritiska.
   - Simulacija dodira na MENU stavke i promjenu kategorija kotačićem/dodirom.
2. **Vizualna verifikacija**:
   - Prikazivanje stvarnih kadrova preko `CameraGuiWindow` i `DmpPicaRasterizer` koji dekodiraju autentične PICA200 GPU pakete.
   - Potvrda rada modova u čistom softverskom okruženju prije slanja na fizičku kameru.
