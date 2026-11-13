# E0484 — The display entry points are called through pointers, not directly

Date: 2026-11-13. Offline only: the a6400 packaged image, no camera, no execution.

The plan for this task was to trace one capability from a button event to a display call. The
trace did not complete, and the reason is more useful than the trace would have been: the display
entry points have no direct callers at all. Their addresses are taken as data, so the call goes
through a function pointer that no direct-call graph can follow.

## 0. Short answer

1. **There is no `ObjDisplay_Start` in this image.** E0021 listed that name from a string scan;
   the a6400, a6600, a6100A and ZV-E10 libraries all define exactly four display symbols:
   `ObjDisplay_Create`, `ObjDisplay_Destroy`, `ObjDisplay_RegisterCommand`,
   `ObjDisplay_UnregisterCommand`. A plan that traced to `ObjDisplay_Start` would have chased a
   string.
2. **None of the four has a direct caller.** `callers_of` returns an empty list for `Create` and
   `RegisterCommand`, and their addresses appear in the image as **data**, once each — the
   signature of a function pointer being stored, not of a call.
3. **The input handler is reachable and populated.** `snd_InfraInputEvent_to_InputServant` has 15
   direct callees, two of them named. The graph works; the display side simply is not connected
   to it by a direct edge.
4. **A defect in the graph was found and fixed on the way**, without which no trace could ever
   have worked: call addresses were looked up exactly, but a call sits *inside* its function, so
   every caller read as `sub_XXXXXXXX` — 555,069 callers, zero named.

## 1. Measured

| measurement | value |
| --- | --- |
| `.text` | `0x104910`, 13,849,456 bytes |
| defined code symbols | 1,852 |
| direct calls | 555,069 |
| named → named edges | **6,713** after the fix, 0 before |
| distinct named callers | 1,386 |
| direct callees of the input handler | 15 (2 named) |
| direct callers of `ObjDisplay_Create` | **0** |
| occurrences of `ObjDisplay_Create`'s address as data | 1 |

## 2. Why the trace cannot complete

```bash
python3 -I tools/research/capability_path.py \
    --image <tree>/libObj.so \
    --start snd_InfraInputEvent_to_InputServant --end ObjDisplay_Create --max-depth 12
# no direct-call path ... within 12 hops
```

Three separate facts stand behind that line:

- the target has no direct callers (§0.2);
- its address is stored as data, which is what a dispatch table or a vtable entry looks like;
- the graph in `callgraph.py` follows direct `bl`/`blx` only, by design — it reports
  `unresolved` rather than inventing an edge through a register.

So the route exists at runtime and is invisible to a static direct-call graph. Recording that is
the finding. Claiming a path would have required following a pointer through memory whose
contents depend on which object was constructed, which this tool deliberately does not guess.

## 3. Method and the check that mattered

```bash
python3 -I tools/research/capability_path.py --image <tree>/libObj.so --start <a> --end <b> --depth 6
python3 -c "import callgraph; g=callgraph.build_callgraph('<tree>/libObj.so'); \
  print(callgraph.callers_of(g,'ObjDisplay_Create'))"
```

The self-check that caught the graph defect was a count of named-to-named edges. It was 0, which
cannot be true of a 20 MB C++ application, so the lookup was examined rather than the count
explained away. `build_callgraph` now resolves a call address to the symbol that *contains* it,
using a bisect over sorted symbol starts.

## 4. Alternative explanations

- **"The display symbols are dead code."** Possible but not established: their addresses being
  taken once each is what a registered callback looks like, and `ObjDisplay_RegisterCommand`
  exists precisely so a caller can register. Dead code would more likely be absent entirely.
- **"The path exists but is longer than 12 hops."** Excluded for this pair, because a route
  through any number of hops still needs a first edge into `ObjDisplay_Create`, and there is
  none. The depth bound is not what blocks it.
- **"The names came from a different build."** E0021 drew `ObjDisplay_Start` from a string
  listing; the symbol table of four separate bodies shows four names and not that one. The string
  may belong to a body or era this corpus does not contain.

## 5. Confidence and limitations

- **Verified:** the four symbol names on four bodies; zero direct callers for two of them; one
  data occurrence of each address; 6,713 named-to-named edges after the fix; 15 callees of the
  input handler.
- **Not verified:** that the pointer route is the mechanism — that needs either a dispatch-table
  walk or runtime observation. This record establishes the absence of a direct edge, not the
  identity of the indirect one.
- **Not claimed:** anything about what a display symbol does when called.

## 6. Dependent implementation

`tools/research/capability_path.py` (path walk, `describe_path`, `sharing_verdict`) and a fix in
`tools/research/callgraph.py`. 20 tests across the two modules. `sharing_verdict` encodes the
correction this project already needed once: any differing function symbol means "separate
kernels", no matter how many symbol names match.

## 7. Next experiment

Walk the dispatch table: find where `ObjDisplay_Create`'s address is stored, which structure
holds it, and what writes that structure. A direct-call graph cannot answer this; a data-flow
search from the stored address can, and it is the natural next step rather than a deeper call
trace.
