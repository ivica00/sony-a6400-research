# E0157: Nativni EP0 konfiguracijski odgovor

Datum: 2026-11-08. Nastavak E0156. Ovaj korak ne pristupa kameri.

## Riješeni problem

Originalni Sony make_config_desc serijalizira cijelu konfiguraciju pa tek na
kraju ograničava povratnu duljinu na wLength. Umetanje UVC IAD-a nakon što
je rezultat već skraćen na 9-byte zaglavlje nije isto što i izrada pune
konfiguracije. Live integracija mora dosljedno prijaviti 173 bajta i u
kratkom zaglavlju i u punom odgovoru, bez upisa preko stvarnog outputa.

## Implementacija

Dodana ARM funkcija `a6400_uvc_ptp_candidate_config_reply` u
`tools/native_camera/uvc_ptp_descriptors.{c,h}`:

1. Prihvaća samo standardni IN GET_DESCRIPTOR za configuration 0, High
   Speed. Potvrđuje da gadgetcore koristi upravo caller-owned kandidat.
2. Provjerava topologiju prije poziva izvornog serializera: counts,
   alternate/endpoint/extra pointere i duljine. Time se originalni
   neograničeni zapis ne poziva s nepoznato velikim stablom.
3. Koristi lokalni sinkroni request s wLength=512 i 512-byte staging buffer.
   Originalni setup i output do tada se ne mijenjaju.
4. Poziva stvarni originalni make_config_desc na 602bbc54. Očekuje točno
   165 bajtova, umeće IAD stvarnom kompajliranom ARM funkcijom i potvrđuje
   konačnih 173 bajta.
5. Kopira min(originalni wLength,173) bajtova tek nakon svih provjera.
   Premalen caller output vraća -28 prije serijaliziranja; pogrešan
   zahtjev/topologija vraća -22. Output koji se preklapa sa setupom ili
   kandidat stablom odbija se. Native negativni serializer rezultat se
   propagira, ali ta grana nije zasebno fizički dokazana.

Caller mora stabilizirati descriptor topologiju tijekom cijelog poziva.
Ovdje nije uveden mutex niti dokazana višedretvena live integracija. Lokalni
request služi samo sinkronom originalnom serializeru koji je u provjeri
izvršen do povratka; ne šalje se asinkronom EP0 completionu.

## Provjera stvarnog kompajliranog puta

Proširen `tools.research.build_uvc_ptp_descriptor_candidate` izvršava:
kompajlirani reply wrapper -> originalni Sony serializer/memcpy ->
kompajlirani IAD -> kopiranje u caller buffer. Nema serializer stuba.
Caller-owned kandidat, gadgetcore, speed, setup i stack eksplicitni su
izvanmrežni predlošci. Originalni firmware identiteti ostaju SHA-vezani,
kernel code write-protected i izvršavanje/zapisi ograničeni guardovima.

172 kontrole prolaze: ranije 24, plus 13 pozitivnih zahtjeva po šest provjera
i 14 negativnih slučajeva po pet provjera. To nisu 172 fizička USB testa.

Pozitivne duljine: 0,1,8,9,17,39,40,47,172,173,174,512,65535. U svakoj se
izvorni serializer stvarno zove jednom, output odgovara očekivanom prefiksu,
ostatak buffera ostaje netaknut, setup i nativno stablo ne mijenjaju se.

Negativni slučajevi: other-speed, pogrešan configuration index, recipient,
bRequest/wIndex, nedovoljan kapacitet, tuđa tablica, pogrešna brzina, broj
sučelja/alternateova, preveliki class/endpoint extra blok te output alias.
Svi su odbijeni prije native serializera, bez promjene setupa, stabla ili
output buffera.

Sačuvani rezultati stvarnog kompajliranog wrappera:

- `artifacts/native/uvc-ptp-ep0-e0157/native-ep0-reply-9.bin`.
- `artifacts/native/uvc-ptp-ep0-e0157/native-ep0-reply-173.bin`.
- `artifacts/native/uvc-ptp-ep0-e0157/manifest.json` s hashovima i opaženom
  potrošnjom fixture stacka (nije mjerenje slobodnog live kernel stacka).

Zaglavlje: `09 02 ad 00 03 01 00 80 fa`; wTotalLength=173, tri sučelja.
PTP dio ostaje identičan fizičkom očitanju iz E0153.

```
python -m tools.research.build_uvc_ptp_descriptor_candidate --output-dir artifacts/native/uvc-ptp-ep0-e0157
```

## Granica prije fizičke integracije

Funkcija još nije zamijenila live gadgetcore EP0 hook. Nije dovršena puna
native device-descriptor tablica sa stringovima i device identityjem;
postojeći kandidat dokazuje konfiguracijsku topologiju, ne cijeli USB uređaj.
Full Speed/other-speed odgovor namjerno se odbija umjesto izmišljanja
neprovjerenog profila; prije deploya treba riješiti stvaran fallback ugovor.
Zajednički register/stop/unregister originalnog PTP-a i UVC-a, rollback i
native JPEG/DMM producer također ostaju otvoreni.

Ovi dijelovi nisu povezani s postojećim runtimeom pa puni skup nije ponavljan
nakon E0156 (605 testova prošlo). Nema camera uploadova, modula, feeder
procesa, USB promjene, SD ili trajnih zapisa. Fizička enumeracija i zajednički
UVC+PTP prijenos ostaju nepotvrđeni.
