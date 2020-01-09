# lexibanktools

Personal tools for Lexibank development

## prftool

A tool for writing/debugging orthographic profiles. It is not intended to
generate profiles, which should be done with `lingpy`.

The only command right now is `format`.

```bash
usage: prftool.py [-h] [--wl WL] [--output OUTPUT] [--debug_wl DEBUG_WL]
                  [--grapheme GRAPHEME] [--ipa IPA] [--clts CLTS] [--csv]
                  [--form FORM] [--nonfc] [--nobound]
                  {format} profile

Orthographic profile formatter/linter.

positional arguments:
  {format}             The action to be performed on an orthographic profile.
  profile              Path to the orthographic profile to be manipulated.

optional arguments:
  -h, --help           show this help message and exit
  --wl WL              Path to the relative wordlist to be used for frequency
                       and analysis.
  --output OUTPUT      Path to the output orthographic profile. If not
                       provided, it will be printed to screen.
  --debug_wl DEBUG_WL  Path to the output debug wordlist, if any
  --grapheme GRAPHEME  Name of the grapheme column (default: `Grapheme`).
  --ipa IPA            Name of the IPA column (default: `IPA`).
  --clts CLTS          Path to the CLTS data repos (default:
                       `~/.config/cldf/clts`).
  --csv                Uses commas as separators in the wordlist (default:
                       tabs)
  --form FORM          Name of the form column in the wordlist (default:
                       `Form`)
  --nonfc              Instruct not to perform Unicode NFC normalization in
                       profile and forms.
  --nobound            Instruct not to incorporate automatic boundary symbols
                       to forms.
```

The tool is used to:

- Sort a profile, both in terms of columns (Grapheme, IPA, FREQUENCY,
  CODEPOINTS, and all others in alphabetical order), and entries,
  so it is easily diffable
- List repeated graphemes, differentiating between pure duplicates and
  contradictory information:

```bash
WARNING:__main__:Duplicate (redundant) entry or entries for grapheme [ṣ].
ERROR:__main__:Inconsistency for grapheme [C]: potential mappings ['c', 'ts'].
```

- Inform if the IPA column contains any unrecognized BIPA sound
- Replace all BIPA aliases with the default codepoint(s) (e.g., `λ` to `ʎ`
  and `ʦ` to `ts`), taking care of slash notations
- Apply Unicode NFC normalization to Graphemes and IPA, so users can copy
  from the profile and search in the normalized data
- Generate/update the `CODEPOINTS` field with the correct Unicode Codepoint
  string when necessary
- Generate/update frequency counts on the actual data (wordlist)
- Remove entries which are not used
- Generate a debugging segmentation which highlights which entry was
  matched for each substring, e.g.:

  | ID | Form | Debug segments |
  |----|------|----------------|
  | Tirua-112_live-1 | mO.ˈNEj | {^}/{} {m}/{m} {O}/{ö} {.}/{NULL} {ˈ}/{NULL} {N}/{ŋ} {E}/{ë} {j}/{j} {$}/{} |
  | Nuevatolten-205_only-1 | ˈTI.SU | {^}/{} {ˈ}/{NULL} {TI}/{cɪ} {.}/{NULL} {S}/{ʃ} {U}/{ʊ} {$}/{} |
  | Mariquina-58_moon-1 | kE.ˈjING | {^}/{} {k}/{k} {E}/{ë} {.}/{NULL} {ˈ}/{NULL} {j}/{j} {ING}/{ɪŋ} {$}/{} |
