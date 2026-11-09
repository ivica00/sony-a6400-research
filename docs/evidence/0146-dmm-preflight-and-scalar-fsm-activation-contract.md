# E0146: DMM Preflight, ScalarInfra FSM Activation Contract, and Shooting Stage Analysis

Datum: 2026-11-07. Svi zapisi na kameri strogo ograničeni na `/tmp_bt`; bez SD/NAND/backup/preload/boot izmjena. Niti jedan blokirajući poziv `0x8120` (`ScalarJpegOpen`) nije izdan na živoj kameri. Debugger PID 703 aktivan i responsivan u Mass Storage načinu. Svih 599 testova emulatora prolazi.

## 1. DMM Preflight na živoj kameri (`/proc/udm/`)

Na živoj kameri lociran je i ispitan DMM podsustav kroz `/proc/udm/`:
- `/proc/udm/dmm_units`: Popis aktivnih jedinica. Jedinice `UnitType 0x276` (JPEG sequence buffer) i `UnitType 0x274` (JPEG frame buffer) **nisu prisutne**.
- `/proc/udm/dmm_rule`: Trenutno pravilo alokacije je isključivo `[0000] < ffff < ffff < ffff < ffff < ffff < ffff < ffff`.
- `/proc/udm/dmm_extents`: Root extent `0005` (tip `0x000004ec`) je mapiran na fizičku adresu `0x14000000` (veličina 96 MB, `0x06000000`).
- Usporedbom s `DmmConfig.bin` (ilc8g-astra):
  - `UnitType 0x274` (JPEG frame buffer, 12 slotova po 256 KiB, `0x40000`) koristi extent `0x32e`.
  - `UnitType 0x276` (JPEG sequence buffer, 2 MiB, `0x200000`) koristi extent `0x333`.
  - Oba extenta nalaze se pod parent tablicom `0x32f` -> `0x41d` -> root extent `0x4ec` (`0x14000000`).
  - U Mass Storage načinu rada pravilo `0` ne urezuje extente `0x32e` i `0x333`. Poziv `dmm_unit_ctrl_Alloc` za `0x276` u ovom načinu deterministički vraća status `-3` (`0xfffd`, `handle = 0xffff`).

## 2. Prevencija blokade dretve u `ScalarJpegOpen_candidate` (`0x63a918c0`)

Dekompilacija `ScalarJpegOpen_candidate` (`0x63a918c0`) u `oril-jpeg-open-close-e0144`:
```c
while (true) {
    iVar2 = FUN_63a8c7b8(0x276, 0, auStack_8c);
    *(undefined2 *)(param_1 + 0x78) = local_88;
    if (iVar2 == 0) break;
    *(undefined2 *)(param_1 + 0x78) = 0xffff;
    local_28 = 2000; // 2000 ms sleep
    func_0x635dd4a8(0x910041, local_40);
    if (uVar4 == 0x14) {
        func_0x63c26e94("[SFRA][ERROR] MEMORY SHORTAGE!!! file=%s line=%d", "ScalarInfraSequenceJpeg.cpp", 0x65);
    } else if (15000 < uVar4) {
        // prekid tek nakon 15.000 iteracija (> 8 sati!)
    }
    uVar4 = uVar4 + 1;
}
```
**Zaključak:** Zahvaljujući Fazi 1, spriječeno je slanje neprovjerenog `0x8120` (`SET_PATH(OPEN)`), čime je `ScalarInfraAsyncMain` dretva sačuvana od trajne 8-satne blokade.

## 3. Analiza internog ScalarInfra FSM-a (`0x01670464`)

Disasembliranjem i dekompilacijom `av-cam-camera-original.bin` (baza `0x635c6000`):
1. **Vanjski prijemnici**:
   - `CMD_JPEG` (`0x50` na `0x0167046a`, funkcija `FUN_63a90a84`) prepakira parametre (uključujući `path_enable` na `+0x40`) i šalje DataflowInfra poruku na red **`0x01670464`**.
   - `CMD_LIVEVIEW` (`0x51` na `0x0167046a`, funkcija `FUN_63a90b70`) također šalje na red **`0x01670464`**.
2. **Interni FSM prijelaz (`ScalarInfraPathCmdSetPath`)**:
   - `ScalarInfraPathCmdSetPath::TransPathIdle()` (`0x63a8fc94`):
     - Poziva `msg->GetStatus()`.
     - Ako je status `1`, poziva `SendOpenPathCmdToAsyncTask()` (`0x63a8fa6c`) i prelazi u stanje `2`.
     - `SendOpenPathCmdToAsyncTask()` šalje internu poruku `0x8120` (`SET_PATH(OPEN)`) prema `ScalarInfraAsyncMain`.
     - Ako je status `0`, poziva `0x63a8fbec` koja šalje internu poruku `0x8110` (`SET_PATH(CLOSE)`).
   - `ScalarInfraPathCmdSetPath::TransPathLiveView()` (`0x63a90100` -> `0x63a99810`):
     - Iterira od 0 do `0x31` (selektori sekvenci, uključujući `0x30`/`0x31` za JPEG) i traži alokaciju DMM `UnitType 0x2d5`.

## 4. Arhitektonska implikacija za opciju B (Sensor / LiveView)

U USB Mass Storage načinu rada:
- Kamera je u pasivnom diskovnom načinu, senzor je u stanju pripravnosti (standby/isključen), a DMM drži samo pravilo `0` (nema aktivnih međuspremnika za snimanje).
- Da bi senzor počeo generirati stvarne 720p kadrove:
  1. DMM pravilo mora prijeći u stanje snimanja (Shooting mode / PC Remote), u kojem se alociraju extents `0x32e` i `0x333` pod `0x14000000`.
  2. BIONZ X ISP i skalar počinju ciklički upisivati JPEG frameove u 12 slotova kružnog međuspremnika na `0x643c3708 + 0xf4` (`ready = 1`).
  3. Koherentni UVC feeder čita `ready = 1` slotove, prenosi ih u DMA međuspremnik (`0x05280000`) i šalje hostu preko UVC streaming sučelja.

## 5. Regresija i stabilnost

- Svi testovi emulatora: **599 testova prošlo u 14.884s**.
- Stanje kamere: MSC način rada, debugger PID 703 netaknut i responsivan, modul `usbg_video` uklonjen, bez izmjena na flashu ili SD kartici.
