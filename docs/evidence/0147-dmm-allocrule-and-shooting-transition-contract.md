# E0147: DMM AllocRule Architecture and Shooting State Transition Contract

Datum: 2026-11-07.  
Opseg: Sony ILCE-6400 (firmware 2.00, kernel 3.0.27_nl-rt106+).  
Cilj: Utvrditi mehanizam postavljanja DMM pravila (`AllocRule`), razlog nealociranosti `0x276`/`0x274` u Mass Storage načinu rada te arhitekturu prelaska u aktivno stanje snimanja (Shooting / PC Remote) za preuzimanje izvornog 720p 30 FPS JPEG video toka za CinemaHUD prema Windows inbox `usbvideo.sys`.

---

## 1. DMM AllocRule i Struktura Pravila u Kernelu (`dmm.ko`)

Analiza disasembliranog koda modula `dmm.ko` i raspakiranog `DmmConfig.bin` (ilc8g-astra, 77.108 bajtova) utvrdila je točan algoritam provjere pravila alokacije:

1. **Format Zaglavlja Tablice Extenata (`dmm_ext_tbl_Init`, 80 bajtova po zapisu)**:
   - Svako zaglavlje extenta u `DmmConfig.bin` sadrži 20 riječi (80 bajtova).
   - Riječi 4 do 19 (od pomaka `+0x10` do `+0x4f`) čine niz od točno 64 bajta koji predstavljaju aktivacijske atribute za 64 moguća pravila alokacije (`rule` od 0 do 63):
     $$\text{rule\_byte} = \text{header}[0x10 + \text{rule}]$$

2. **Verifikacija Pravila u Kernelu (`0x0000a658` unutar `dmm_ext_ctrl_AllocExtent`)**:
   - Prilikom poziva alokacije extenta, kernel dohvaća trenutno aktivno pravilo pozivom `dmm_ext_ctrl_GetCurrentAllocRule`:
     ```arm
     0x0000b720: add r0, r4, #8
     0x0000b724: bl  dmm_ext_ctrl_GetCurrentAllocRule
     0x0000b738: bl  #0xa658
     ```
   - Unutar funkcije `0xa658`, kernel provjerava bajt pravila na zaglavlju extenta:
     ```arm
     0x0000a78c: mov  r2, #0x50           ; 80 bajtova po zaglavlju
     0x0000a790: mla  r3, r2, r0, r3      ; adresa zaglavlja
     0x0000a794: add  r3, r3, r8          ; r8 = broj pravila (0..63)
     0x0000a798: ldrb sl, [r3, #0x10]     ; sl = header[0x10 + rule]
     0x0000a79c: cmp  sl, #0              ; je li bajt != 0?
     0x0000a7a0: bne  #0xa7b0             ; DA: extent je dopušten
     0x0000a7a4: b    #0xa7d0             ; NE (0): preskoči extent (odbij alokaciju)
     ```
   - Ako je `sl == 0` ili ne zadovoljava minimalni atribut (`sl < r0`), funkcija `0xa658` vraća `-1`, a `dmm_unit_ctrl_Alloc` vraća kod greške `-3` (`ERR_DMM_HANDLE`) uz ručku `0xffff`.

3. **Stanje u Mass Storage Načinu Rada (`/proc/udm/dmm_rule`)**:
   - Na živoj kameri `/proc/udm/dmm_rule` glasi:
     ```text
     Information on AllocRule.
     [0000] < ffff < ffff < ffff < ffff < ffff < ffff < ffff
     ```
   - Aktivno pravilo je isključivo `[0000]` (Rule 0).
   - Root extent `0005` (tip `0x000004ec`, 96 MB na fizičkoj adresi `0x14000000`) mapiran je u kernelu, ali ima točno nula alociranih pod-extenata jer se cjevovod senzora i ISP-a ne inicijalizira u standby načinu USB pohrane.

---

## 2. Prijelaz Stanja Snimanja u Aplikaciji Kamere (`av-cam-camera-original.bin`)

Dekompilacijom korisničke aplikacije kamere (`av-cam-camera-original.bin`, base `0x635c6000`) lociran je izvorni podsustav video izlaza i postavljanja DMM pravila:

1. **Izvorni Kod Video Cjevovoda (`SyncYCOut.cpp`)**:
   - Niz tekstualnih referenci potvrdio je izvorne C++ komponente:
     - `SyncYCOut.cpp` (upravljanje sinkronim YCbCr video izlazom)
     - `ScalarInfraSequenceLiveView.cpp` (LiveView JPEG sekvenca)
     - `ScalarInfraSequenceJpeg.cpp` (JPEG kodiranje i ring buffer)
     - `sfmc_enc_timing_i_a1_diadem_streaming_30p25p.cpp` (vremensko vođenje 30 FPS video toka)
   - U `SyncYCOut.cpp` (`0x63939486`) i povezanim funkcijama:
     ```arm
     0x63939482: mov  r0, r6
     0x63939484: movs r1, #5              ; Rule 5 (Shooting / LiveView)!
     0x63939486: bl   #0x63d51ff0
     ```
   - Svih 8 pozivatelja funkcije `0x63d51ff0` (`0x638b812c`, `0x638b821c`, `0x639250c2`, `0x63928834`, `0x63939486`, `0x6393a5b6`, `0x6393ad3a`, `0x6394ab84`) prosljeđuju `r1 = 5`!

2. **DMM Prijenos i UIPC Red `0x0061003c`**:
   - `0x63d51ff0` poziva `0x6394f820`, koji šalje poruku s događajem 6 i željenim pravilom na Infra upravljač.
   - Prijelaz u Rule 5 aktivira DMM alokacije extenata `0x32e` (UnitType `0x274`, 12 slotova po 256 KiB) i `0x333` (UnitType `0x276`, 2 MiB sequence buffer) unutar 96 MB prozora na `0x14000000`.

---

## 3. Arhitektura USB Načina Rada (`libUsbControl.so` i CinemaHUD)

1. **Usporedba Načina Rada**:
   - **Mass Storage (MSC)**:
     - Pokreće se `libInfraMscServer.so` (učitana u PID 149 na `0x0c6d5000`).
     - Senzor, BIONZ X ISP i video koder miruju. Ekran prikazuje statički natpis "USB Mode: Mass Storage".
     - DMM drži Rule 0; kružni međuspremnik na `0x643c3708 + 0xf4` je prazan (`ready = 0`).
   - **PC Remote / PTP (CinemaHUD ugovor iz E0137)**:
     - Kamera je u punom radnom stanju snimanja (Shooting mode). Senzor i ISP su aktivni.
     - Pokreće se `libInfraStreamingServer.so` i PTP podsustav (`libptp.so`).
     - JPEG ring buffer se kontinuirano puni živim sličicama.
     - CinemaHUD dohvaća sličice putem PTP transakcije `PTP_OC_GetObject(0xFFFFC002)`.

2. **Kompatibilnost s Debuggerom**:
   - Root debugger (PID 703) koristi Sony vendor ekstenziju (Feature `0x23`) koja je podržana i na MSC (`SonyMscExtCmdDevice`) i na PTP/MTP (`SonyMtpExtCmdDevice`).
   - Verificirano u E0137: Debugger ostaje u potpunosti dostupan i responzivan u PC Remote načinu rada.

---

## 4. Regresijska Verifikacija

- Cjelokupni skup testova emulatora uspješno je izvršen:
  ```text
  Ran 599 tests in 14.681s - OK
  ```
- Fizička kamera: Povezana putem USB-a, Mass Storage način rada, debugger PID 703 aktivan i responzivan.
- Svi zapisi na kameri i dalje strogo ograničeni na RAM `/tmp_bt`.
