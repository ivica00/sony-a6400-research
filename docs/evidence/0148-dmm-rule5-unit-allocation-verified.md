# E0148: DMM Rule 5 Activation and Native Unit Allocation Verified

Datum: 2026-11-07.  
Opseg: Sony ILCE-6400 (firmware 2.00, kernel 3.0.27_nl-rt106+).  
Cilj: Provjeriti programsku aktivaciju DMM pravila 5 (`AllocRule 5`) i nativnu alokaciju jedinica `0x276` (JPEG sequence buffer) i `0x274` (JPEG frame buffer) na živoj kameri putem OSAL UIPC reda `0x0061003c`, uz cjelovit životni ciklus oslobađanja resursa i verifikaciju regresije.

---

## 1. DMM UIPC Protokol i Struktura Poruka (`QUEUE_DMM 0x0061003c`)

Dekompilacijom tablice `msg_hdlr` u kernel modulu `dmm.ko` (offset `0x80` u `.rodata`) i disasembliranjem upravljačkih funkcija utvrđen je točan binarni format poruka za komunikaciju preko `/dev/uipc`:

1. **Zaglavlje i Raspored Polja Poruke**:
   - `msg[-4]` (OSAL reply queue header): `reply_qid` (dinamički red dodijeljen putem `ioctl 0x8000000c`, op `0x2a`).
   - `msg[0x00..0x01]` (`uint16_t`): Opcode naredbe.
   - `msg[0x02..0x03]` (`uint16_t` ili `uint8_t`):
     - Za `SetAllocRule` (20 / `0x14`): Broj pravila (`rule`, npr. 5 za Shooting / LiveView).
     - Za `FreeUnit` (4 / `0x04`): Ručka jedinice (`handle`).
   - `msg[0x04..0x07]` (`uint32_t`): `unit_type` (npr. `0x00000276` ili `0x00000274`) za `AllocUnitNew` i `GetUnitHandle`.
   - `msg[0x16..0x17]` (`uint16_t`):
     - Za `SetAllocRule`: Način rada (`mode`: `0` = zamjena osnovnog pravila, `0x100` = push na stog, `0x101` = pop sa stoga).
     - Za `AllocUnitNew`: Atributne zastavice (`flags`: `0`).

2. **Podržani Opkodovi u `msg_hdlr`**:
   - `[01]` (`0x01`): `dmm_ctrl_AllocUnitNewHdlr`
   - `[04]` (`0x04`): `dmm_ctrl_FreeUnitHdlr`
   - `[05]` (`0x05`): `dmm_ctrl_OpenUnitHdlr`
   - `[06]` (`0x06`): `dmm_ctrl_CloseUnitHdlr`
   - `[20]` (`0x14`): `dmm_ctrl_SetAllocRuleHdlr`
   - `[26]` (`0x1a`): `dmm_ctrl_GetUnitHandleHdlr`

---

## 2. Fizička Verifikacija na Kameri

Razvijeni su i pokrenuti samostalni ARM alati bez libc ovisnosti (`probe_dmm_rule_arm`, `test_single_jpeg_pipeline_arm`, `free_both_units_arm`) izravno u RAM direktoriju `/tmp_bt`:

1. **Provjera Stanja Prije Aktivacije**:
   - `GetUnitHandle(0x276)`: vraća status `6`, ručka `0xffff` (odbijeno).
   - `GetUnitHandle(0x274)`: vraća status `6`, ručka `0xffff` (odbijeno).
   - `/proc/udm/dmm_rule`: `[0000]`.

2. **Aktivacija Pravila 5 (`SetAllocRule(5, 0)`)**:
   - `SetAllocRule(5, 0)` vraća status `0` (uspjeh).
   - `/proc/udm/dmm_rule` prelazi u:
     ```text
     Information on AllocRule.
     [0005] < ffff < ffff < ffff < ffff < ffff < ffff < ffff
     ```

3. **Nativna Alokacija Jedinica pod Pravilom 5**:
   - `AllocUnitNew(0x276, 0)`: vraća status `0`, ručka `0x08d0`.
   - `AllocUnitNew(0x274, 0)`: vraća status `0`, ručka `0x08cd`.
   - Očitanje `/proc/udm/dmm_units` potvrdilo je fizičko postojanje i točne adrese u RAM-u kamere:
     ```text
     08cd     00000274  0001    01     00    00    02      00000606  14000000  00040000  0390 < 0388 < 0153 < 0005
     08d0     00000276  0001    01     00    00    02      00000605  14300000  00200000  039c < 0388 < 0153 < 0005
     ```
     - **Jedinica `0x274`**: fizička adresa `0x14000000`, veličina 256 KiB (`0x00040000`).
     - **Jedinica `0x276`**: fizička adresa `0x14300000`, veličina 2 MiB (`0x00200000`).
     - Obje jedinice pripadaju root extentu `0005` (96 MB na `0x14000000`).

4. **Čisto Oslobađanje Resursa i Vraćanje u Početno Stanje**:
   - `FreeUnit(0x08cd)` i `FreeUnit(0x08d0)` izvršeni putem `free_both_units_arm`.
   - `/proc/udm/dmm_units` potvrđeno potpuno čist (0 zaostalih ručki).
   - `SetAllocRule(0, 0)` vratio je `AllocRule` na `[0000]`.

---

## 3. Nalazi o Sinkronizaciji Video Cjevovoda (`Sugilite` ISP)

1. Prilikom slanja `SET_PATH start (1280x720, 30 FPS)` u Mass Storage načinu rada:
   - Dretva 355 (`THREAD_INFRA0`) komunicira s ISP drajverom putem `sugilite_ioctl`.
   - Inicijalizacija hardvera zahtijeva dulje od 800 ms. Preuranjeni prekid klijentskog procesa uzrokuje dmesg grešku:
     ```text
     [K]**UIPC ERROR** osal_snd_msg: snd to invalid qid 02d96104 != 00000000 @ 635dd483
     ```
   - Za pouzdan rad klijentski timeout za `SET_PATH start` mora biti postavljen na minimalno 3000 ms.

---

## 4. Regresijska Verifikacija

- Cjelokupni skup testova emulatora uspješno je izvršen:
  ```text
  Ran 599 tests in 15.092s - OK
  ```
- Fizička kamera: Mass Storage način rada, debugger PID 703 responzivan, `/proc/udm/dmm_units` čist, nema curenja memorije.
- Svi zapisi na kameri i dalje strogo ograničeni na RAM `/tmp_bt`.
