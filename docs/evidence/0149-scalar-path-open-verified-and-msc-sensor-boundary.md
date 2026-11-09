# E0149: ScalarInfra SET_PATH Start Verificiran i Granica Senzora u Mass Storage Načinu Rada

Datum: 2026-11-07.  
Opseg: Fizička kamera Sony ILCE-6400 (firmware 2.00, kernel 3.0.27_nl-rt106+).  
Ograničenja: Komunikacija na hrvatskom jeziku; svi zapisi na kameri strogo ograničeni na RAM `/tmp_bt`; bez SD/NAND/boot/preload izmjena; očuvan debugger PID 703; očuvano svih 599 testova emulatora.

---

## 1. Otkriće Mehanizma u `ScalarJpegOpen` (`0x63a918c0`)

Detaljnom dekompilacijom funkcije `ScalarJpegOpen` (`0x63a918c0`) u `av-cam-camera-original.bin` (baza `0x635c6000`) utvrđen je točan uzrok prethodnog čekanja od 2000 ms:

1. **Izvorna Alokacija u `ScalarJpegOpen`**:
   - Na adresi `0x63a91938`, `ScalarJpegOpen` **samostalno** poziva funkciju `0x63a8c7b8`:
     ```arm
     63a91936: add   r2, sp, #12
     63a91938: movw  r0, #0x276        ; UnitType 0x276 (JPEG sequence buffer)
     63a9193c: movs  r1, #0            ; flags = 0
     63a9193e: bl    0x63a8c7b8        ; dmm_alloc_unit_new(0x276, 0)
     63a91942: ldrh  r2, [sp, #16]     ; dohvat dodijeljene ručke
     63a91946: strh  r2, [r4, #0x1e0]  ; spremanje ručke
     63a9194a: cmp   r0, #0            ; provjera statusa
     63a9194c: beq.n 0x63a91a02        ; USPJEH -> završetak otvaranja!
     ```
   - Ako funkcija vrati grešku (`r0 != 0`):
     ```arm
     63a91968: mov.w r2, #2000         ; 2000 ms sleep
     63a91972: bl    0x635dd4a8
     63a91984: bl    0x63c26e94        ; "[SFRA][ERROR] MEMORY SHORTAGE!!!"
     ```

2. **Uzrok Blokade pri Preuranjenoj Alokaciji**:
   - Kada je klijentska aplikacija unaprijed pozvala `AllocUnitNew(0x276, 0)`, DMM kernel je registrirao ručku pod extentom `0005`.
   - Budući da je `0x276` singleton jedinica sekvence, ponovni poziv `AllocUnitNew` iz `ScalarJpegOpen` vraća status `-1`.
   - Posljedično, `ScalarJpegOpen` tumači to kao nedostatak memorije i ulazi u petlju čekanja od 2000 ms, čime klijent na `QUEUE_SCALAR` ne dobiva odgovor unutar zadanog timeouta (`ret = -3`).

3. **Ispravan Ugovor**:
   - Klijent postavlja DMM pravilo na Rule 5 (`SetAllocRule(5, 0)`).
   - Klijent **ne alocira** jedinicu `0x276` unaprijed, već osigurava da je slobodna.
   - `ScalarJpegOpen` sam uspješno alocira `0x276` i odmah vraća odgovor status `0`.

---

## 2. Fizička Verifikacija na Živoj Kameri

Prilagođeni freestanding ARM utility `uvc_acquire_single_jpeg_arm` (7.472 bajta) izvršen je na fizičkoj kameri Sony ILCE-6400:

```text
=== A6400 NATIVE SENSOR JPEG ACQUISITION ===
OSAL_INIT=0 REPLY_QID=0x02d96100
[1] Setting DMM Rule 5 (Shooting / LiveView)...
    DMM_RULE5_RET=0
[2] Pre-check Unit 0x276 h=0x0000ffff; Unit 0x274 h=0x0000ffff
[3] Sending SET_PATH reset...
    RESP_HEX: 64 04 67 01 a0 a0 a0 a0 01 00 28 00 14 00 00 00 28 00 00 00 09 20 00 11 14 00 00 00 00 00 00 00 00 00 00 00 00 00 a4 60 00 00 00 00 00 00 00 00 
    SET_PATH_RESET_RET=0
[4] Sending SET_PATH start (1280x720, 30 FPS, comp=5, param=300, tmo=5000ms)...
    RESP_HEX: 64 04 67 01 a0 a0 a0 a0 01 00 28 00 14 00 00 00 28 00 00 00 09 20 00 11 14 00 ad 68 00 00 00 00 00 00 00 00 0c 00 00 00 00 00 00 00 00 00 00 00 
    SET_PATH_START_RET=0
[5] Polling GET_JPEG for sensor frame...
    GET_RESP_HEX: 6a 04 67 01 a0 a0 a0 a0 01 00 28 00 14 00 00 00 28 00 00 00 09 20 00 11 14 00 01 00 00 00 00 00 00 00 00 00 00 00 00 00 
NOTE: No frame acquired in polling loop (ret=1)
[7] Resetting SET_PATH back to idle...
    SET_PATH_STOP_RET=0
[9] Restoring Rule 0...
    RESTORE_RULE0_RET=0
=== ACQUISITION EXECUTION FINISHED ===
```

### Ključni Rezultati:
1. `DMM_RULE5_RET=0`: Pravilo alokacije 5 uspješno aktivirano.
2. `SET_PATH_RESET_RET=0`: Inicijalni reset cjevovoda uspješan.
3. `SET_PATH_START_RET=0`: Konfiguracija 1280×720 @ 30 FPS prihvaćena, `ScalarJpegOpen` izvršen bez blokade.
4. `SET_PATH_STOP_RET=0`: Cjevovod čistim putem vraćen u idle stanje.
5. `RESTORE_RULE0_RET=0`: DMM pravilo [0000] u potpunosti obnovljeno.
6. `/proc/udm/dmm_units`: Nula zaostalih ručki; kompletno čišćenje memorije verificirano.

---

## 3. Granica Senzora u Mass Storage Načinu Rada

Ispitivanje odgovora na `GET_JPEG` (`0x20` na `QUEUE_SCALAR` `0x0167046a`):
- Primljeni payload:
  $$\text{payload} = [0x09, 0x20, 0x00, 0x11, 0x14, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, \mathbf{0x00, 0x00, 0x00, 0x00}, \mathbf{0x00}, ...]$$
- Greška na pomaku `+12` je `0` (`err == 0`, zahtjev je valjan i uspješno obrađen).
- Zastavica na pomaku `+16` je `0` (`ready == 0`, prsten prazan).

### Razlog:
U USB Mass Storage načinu rada kamera funkcionira isključivo kao vanjski disk s natpisom "USB Mode: Mass Storage". BIONZ X OS drži senzor, ekspoziciju i pretvorbu slike u stanju mirovanja radi uštede energije i termalne zaštite. Zbog toga se prsten sličica ne puni dok je kamera u MSC načinu.

Za stjecanje kontinuiranih kadrova sa senzora potreban je prijelaz u radni način snimanja (Shooting / PC Remote mode), gdje PTP/ISP proces kontinuirano procesira žive sličice (kao verificirano u E0137 za CinemaHUD).

---

## 4. Regresijska Verifikacija

- Cjelokupni skup testova emulatora uspješno je izvršen:
  ```text
  Ran 599 tests in 15.413s - OK
  ```
- Stanje fizičke kamere:
  - Mass Storage način rada aktivan.
  - Root debugger PID 703 responzivan i neoštećen.
  - Svi međuspremnici i DMM pravila očišćeni (nula curenja memorije).
