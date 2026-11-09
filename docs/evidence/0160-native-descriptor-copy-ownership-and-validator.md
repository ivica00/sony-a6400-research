# E0160: Native kopija deskriptora i vlasništvo

Datum: 2026-11-08. Nastavak E0159. Nema fizičkog pristupa kameri.

## Važna korekcija integracijskog ugovora

Originalni Sony save_desc_tbl na602bc550 ne postavlja gc+6c na callerov
descriptor objekt. Alocira88-bajtni root, kopira ga i zatim duboko kopira
speed/config grupe i jezične/string objekte. Na602bc5c8 odmah upisuje novi
root u gc+6c. Primjer nested ownership zapisa jest602bc770: novi language
array pointer ide u native root+3c.

Zato zahtjev `gc->desc_tbl == caller_template` iz ranijeg shared reply
kandidata ne bi bio valjan nakon stvarnog save_desc_tbl. E0159 dokazivao je
izvanmrežnu serijalizaciju nad caller-owned objektom, ne kompatibilnost s
native instaliranom kopijom. Ovaj korak izričito popravlja tu granicu.

## Implementacija

Dodana `a6400_uvc_ptp_validate_native_copy(template,native_table)`:

- Template mora biti prethodno provjereno, stabilno HS/FS/string stablo.
- Native root smije biti na drugoj adresi; moraju se podudarati speed
  polja/countovi i sadržaj VID/PID/bcdDevice/string indeksa metadata.
- Bounded obilazak potvrđuje isti broj configuration/interface/alternate
  objekata, iste klase i brojeve sučelja, native endpoint bajtove i VC/VS
  payloadove. Dopušta različite stvarne allocation pointere.
- Jezik, string indeksi/duljine i svi payload bajtovi moraju biti jednaki
  templateu. Nepoznati SS config ili dodatni copy/companion blok odbija se.

Jedinstveni descriptor reply koristi ovu provjeru i potom izvornim Sony
funkcijama serijalizira stvarno aktivni native root iz gc+6c. Ne prepisuje
gc na template, ne uvodi zamjenski gadgetcore i ne zaobilazi originalno
upravljanje kopijama.

Validator nije provjera čitljivosti proizvoljnih adresa. Caller mora dokazati
da graph dolazi iz odgovarajućeg native allocator/save poziva i spriječiti
njegovu promjenu ili oslobađanje tijekom provjere i serijalizacije. Nema
novog live mutexa ili gotovog register/stop/unregister puta.

## Izvanmrežni dokaz

Builder stvara eksplicitni neovisni relokacijski graph fixture: svaki config,
interface array, alternate, endpoint array, class payload, language, string
entry i string payload dobiva drugu adresu. To nije emulacija uspješnog
native allocator poziva niti dokaz njegovih return vrijednosti.

Stvarni kompajlirani validator prihvaća taj graph. Stvarni Sony device,
config, string, qualifier i other-speed serializeri kroz naš reply put za
obje brzine daju iste bajtove kao template. Ni template ni copy fixture ne
mijenjaju se. Neispravni count/pointer-null, wire broj, VC međureferenca,
video adresa81 koja se sudara s PTP-om, FS packet veličina, serijski sadržaj
i LANGID odbijaju se prije odgovora bez output zapisa.

573 kumulativne kontrole prolaze (prethodnih511 i62 novih). Rezultati:
`artifacts/native/uvc-ptp-native-copy-e0160/manifest.json`. Svi izvorni firmware
identiteti, code/write guardovi i oznake eksplicitnih fixturea ostaju aktivni.
Puni runtime skup nije ponavljan: novi dio nije povezan s aktivnim modulom.

## Obavezno čišćenje i povratak

Originalni free_desc_tbl na602bc3e4 oslobađa native nested objekte, završno
oslobađa root na602bc540 i upisuje nulu u gc+6c na602bc548.
save_desc_tbl failure put na602bcda8 također poziva taj helper.
Sačuvani SHA-vezani originalni prozori:
`artifacts/analysis/uvc-descriptor-ownership-e0160/original-ownership-contract.txt`.

Nova integracija zato mora:

1. Zaustaviti i povući korisnike deskriptora prije izmjene.
2. Sačuvati originalni PC Remote root/stanje kao odvojeno vlasništvo.
3. Zaštititi taj root prije save poziva jer save može izmijeniti gc+6c i
   pri grešci pozvati cleanup. Ne pretpostaviti nepromijenjeno staro stanje.
4. Potvrditi stvarni installed root i sadržaj prije spajanja USB-a.
5. Pri rollbacku nakon quiescencea osloboditi upravo instaliranu native
   kopiju originalnim helperom, pa obnoviti stari PC Remote root/stanje.
   Ne oslobađati caller template niti nepoznatu/tuđu tablicu.

Povijesni legacy shim komentira trenutni root kao static bundle i u restore
putu samo nulira gc+6c. To nije ispravan model za novi shared mod nakon native
save kopiranja i ne smije se preuzeti kao dokaz oslobađanja kopije. Legacy
shim u ovom koraku nije mijenjan niti ponovno pokretan na kameri.

## Granica

Native save/allocate/free cijeli lifecycle još nije izvršen u ovim kontrolama.
Nema integriranog zajedničkog modula, fizičke enumeracije, Windows bindinga,
UVC senzorskih kadrova ili istovremenog PTP upravljanja. Nema uploadova,
promjene USB načina, aktivnih modula, SD ili trajnih zapisa.
