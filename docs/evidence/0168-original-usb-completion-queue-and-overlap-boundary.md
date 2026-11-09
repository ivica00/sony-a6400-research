# E0168 — Izvorni USB completion red i granica preklapanja

Datum: 2026-11-08. Offline nastavak E0167. Nema pristupa kameri ni promjene kernel modula.

`tools/research/probe_uvc_ptp_completion.py` izvršava originalne Thumb instrukcije `UsbIfWrapper::doSyncStartStop` (0x13341) i completion callbacka (0x12de5) iz a6400 libUsbControl.so, SHA-256 `70cd5742fde9eea78c60905e4015531b4c3ab2668d2cb85c934531f451f1211f`.

## Uredan završetak i pogreške

Za stop operaciju originalni kod:

1. Stvara OSAL ID pozivom osal_dynamic_id(0x29,0xca,&global_queue).
2. Poziva doStop; njegov uspjeh ovdje znači samo prihvaćen zahtjev.
3. Čeka osal_rcv_msg_tmo(global_queue,&message,0xffffffff).
4. Vraća prvi 32-bitni status iz odgovora, oslobađa poruku, uništava ID pozivom osal_dynamic_id(0x49,0,queue) i briše global_queue.

U pokusu status -5 iz odgovora ostaje -5. Ako receive vrati 7, kod vraća 7, uništi ID i ne oslobađa neprimljenu poruku. Ako doStop odmah vrati 6, kod ne čeka: uništi ID, briše global i vraća 6. OSAL servisi i doStop izričite su zamjene; ne tvrdi se da je fizičko zaustavljanje izvršeno.

## Completion koristi zajedničku ćeliju

Queue cell nalazi se na relativnoj adresi 0x1eabc. Callback 0x12de5 za događaj 0x10001 čita tu ćeliju, traži 4-bajtnu poruku putem osal_valloc_msg_wait(queue,&message,4,1), zapisuje status iz r2 i poziva osal_snd_msg(queue,message). Nepoznat događaj se ignorira. Pogreška alokacije prekida slanje.

U ovom stop completion putu nema oznake konkretne transakcije, provjere radne dretve, usporedbe očekivanog ID-a ni zaštite da queue nije nula. Nakon čišćenja originalni callback pokušava alokaciju za ID 0. U fixtureu alokacija izričito uspije pa se opaža send(0); stvarni OSAL odgovor na nevaljani ID nije izvršen niti dokazan.

Pokus s dva eksplicitna stoga zaustavlja prvi originalni sinkroni poziv na granici prije doStop s ID-om 0x444. Drugi originalni poziv dolazi na istu granicu i prepiše ćeliju ID-om 0x555. Originalni completion tada alocira i šalje odgovor prema 0x555. Ovo dokazuje da tijela sama ne razlikuju te dvije transakcije, a ne da fizički pozivatelji dopuštaju takvo preklapanje.

## Posljedica za zajednički način rada

Nije dovoljno zaključati samo početak našeg ioctl poziva ili samo upis u CUsb red. Potreban je dokaz vlasništva od početka promjene do završnog callbacka, uključujući odbijanje novih promjena dok prethodna nije završena i sigurno postupanje s kasnim završetkom. Ne smijemo ukloniti ili ponovno koristiti completion red dok ga izvorni callback još može koristiti. Izvorni javni stop i kernel disconnect put ostaju dio istog ugovora.

Sljedeći korak je provjeriti izvorni kontekst pozivanja doSyncStartStop u glavnoj UsbControl obradi poruka i njegovu vezu s completion callbackom. Start completion dodatno čisti descriptor/string resurse; taj ogranak nije izvršen u E0168.

## Rezultat i ograničenja

**22 provjere prolaze**, uključujući šest stvarno razriješenih PLT odredišta. Izvještaj: `artifacts/analysis/uvc-ptp-completion-e0168/manifest.json`; zapis: `artifacts/uvc-ptp-completion-e0168.log`.

Originalna tijela odluka i čekanja izvršena su uz ograničenja izvršavanja i zapisa. OSAL ID, alokacija, receive/send/free i doStop izričite su servisne zamjene. Raspoređivač, stvarne poruke, trajanje callbacka i povratak kamere nisu dokazani. Produkcijski kod nije mijenjan; zadnja puna regresija ostaje 605 testova iz E0164. Modul je i dalje neučitan i `physical_test_ready:false`; senzorski UVC s istodobnom PTP kontrolom ostaje nedovršen.
