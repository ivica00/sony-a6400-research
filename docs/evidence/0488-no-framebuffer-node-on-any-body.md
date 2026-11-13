# E0488 — No packaged body registers a framebuffer node; the display is `dmpgles2`

Date: 2026-11-13. Offline only: thirteen packaged `devno.ko` tables, no camera, no execution.

Another a6400 project lists "on-screen GUI" as a confirmed dead end, saying "the display uses a
proprietary DMP GPU (no `/dev/fb0`)", and then ships a GUI whose whole drawing path opens
`/dev/fb0`. A device-node table settles which of the two is right, and needs no camera.

## 0. Short answer

1. **None of thirteen packaged bodies registers an `fb*` node.** The a6400 publishes 88 device
   nodes, the a7 III 76, the ZV-line bodies 90, and not one is named `fb` anything.
2. **Every body publishes `dmpgles2`**, the node the system's own display stack uses.
3. **So opening `/dev/fb0` by that path cannot succeed on a stock body.** The name is not in the
   table, which means no `mknod` entry exists for it and the standard `/dev` namespace will not
   have it.
4. **This does not say a framebuffer is impossible to obtain.** A node can be created by hand with
   the right major/minor if the driver registers one, and `libObj.so` does reference `/dev/fb0` as
   a string (E0021). What is measured is that the packaged namespace does not publish it.

## 1. Measured

| body | device nodes | `fb*` nodes | display node |
| --- | --- | --- | --- |
| `a6400` | 88 | none | `dmpgles2` |
| `a6600` | 88 | none | `dmpgles2` |
| `a6100a` | 88 | none | `dmpgles2` |
| `zve10` | 90 | none | `dmpgles2` (+ `usb/video`, `usb/audio`) |
| `ILCE-7C` | 90 | none | `dmpgles2` (+ both) |
| `ZV-1` | 90 | none | `dmpgles2` (+ both) |
| `DSC-RX0M2` | 90 | none | `dmpgles2` (+ both) |
| `ILCE-7M3` | 76 | none | `dmpgles2` |
| `ILCE-7RM3` | 76 | none | `dmpgles2` |
| `ILCE-7RM4` | 88 | none | `dmpgles2` |
| `ILCE-7RM4A` | 88 | none | `dmpgles2` |
| `ILCE-9` | 88 | none | `dmpgles2` |
| `ILCE-9M2` | 88 | none | `dmpgles2` |

Major numbers in the table are 248–252, all dynamically allocated; `dmpgles2` is `248:29`.

## 2. Why the two claims differ, and which survives

Both projects are describing something real:

- **"No `/dev/fb0`"** is true of the published namespace: no row in `devno.ko` creates that name.
- **`libObj.so` mentions `/dev/fb0`** is also true: the string is in the binary (E0021), which is
  what makes the "we found a framebuffer" reading attractive.

A string in a library is a possibility the code handles; a row in the device table is what the
system actually publishes. The two are not the same evidence, and only the second answers "will
this path exist when my program runs".

## 3. Method

```bash
A6400_UNPACKED_ROOT=<roots> python3 -m unittest tests.test_fb0_absence -v
# two tests: no body publishes an fb* node, and every body publishes dmpgles2
```

The check parses `udif_devnodes` out of each body's `devno.ko` with the project's existing parser
and asserts both halves — the absence and the presence — so it cannot pass by parsing nothing. It
skips when no unpacked body is available, which is the CI case.

## 4. Alternative explanations

- **"`fb0` is created by udev rather than the module table."** This camera runs a minimal system
  without udev in the packaged image; the nodes come from the fixed table. If a runtime component
  created it dynamically, the table would not show it — that is the one gap, and a live
  `ls /dev` would close it.
- **"The GUI works anyway because it falls back."** Possible: the library that mentions `/dev/fb0`
  may try it and continue. That would make a GUI that draws nothing rather than one that crashes,
  which is consistent with the other project not demonstrating an on-screen result.
- **"The other project uses a different camera build."** All thirteen packaged builds agree, so a
  build difference would have to be a runtime-created node, which loops back to the first point.

## 5. Confidence and limitations

- **Verified:** zero `fb*` rows and one `dmpgles2` row on each of thirteen bodies, from the
  packaged `devno.ko` tables.
- **Not verified:** what a live `/dev` contains. A runtime component could create additional
  nodes, and only a read-only probe on a camera can rule that out.
- **Not claimed:** that drawing on this camera is impossible. The system clearly does draw, through
  `dmpgles2`; the claim is about which path a program must use.

## 6. Dependent implementation

`tests/test_fb0_absence.py`, two tests. It uses `predict_body._devno_nodes`, so the parsing lives in
one place rather than being duplicated for this question.

## 7. Next experiment

A single read-only `ls -l /dev | grep -iE 'fb|dmp'` on any body settles the last gap in §4. It needs
a camera or a preserved probe capture, and it is the cheapest possible next step.
