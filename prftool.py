#!/usr/bin/env python3

# TODO: remove redundant complex rules (ab = a + b)
# TODO: properly emulate spaces?

# Import Python default libraries
from collections import defaultdict
import argparse
import copy
import csv
import itertools
import logging
import pathlib
import random
import re
import unicodedata

# Import other libraries
import pyclts
from pyclts import CLTS


def normalize(text):
    """
    Normalize Unicode data.
    """

    # Only simple NFC normalization for the time being
    return unicodedata.normalize("NFC", text)


def unicode2codepointstr(text):
    """
    Returns a codepoint representation to an Unicode string.
    """

    return " ".join(["U+{0:0{1}X}".format(ord(char), 4) for char in text])


def ipa2types(ipa_text, clts):
    # Obtain only the BIPA grapheme, removing left slash if any
    ipas = [
        token if "/" not in token else token.split("/")[1]
        for token in ipa_text.split()
    ]

    # Get a textual representation
    types = [
        type(clts.bipa[token]).__name__ if token != "NULL" else "NULL"
        for token in ipas
    ]

    return " ".join(types)


def ipa2sca(ipa_text, clts):
    # Obtain only the BIPA grapheme, removing left slash if any
    ipas = [
        token if "/" not in token else token.split("/")[1]
        for token in ipa_text.split()
    ]

    # Get a textual representation
    sca = clts.soundclass("sca")
    types = [
        clts.bipa.translate(token, sca) if token != "NULL" else "NULL"
        for token in ipas
    ]

    return " ".join(types)


def read_profile(filename, args):
    """
    Read a profile as a dictionary data structure.

    This will also Unicode normalize the profile, if requested.
    """

    profile = []
    with open(filename) as profile_file:
        reader = csv.DictReader(profile_file, delimiter="\t")
        for row in reader:
            if not args.nonfc:
                row[args.grapheme] = normalize(row[args.grapheme])
                row[args.ipa] = normalize(row[args.ipa])

            profile.append(row)

    return profile


def check_consistency(profile, clts, args):
    """
    Check a profile for consistency, logging problems.
    """

    # Collect all grapheme -> ipa possibilities
    mapping = defaultdict(list)
    for entry in profile:
        mapping[entry[args.grapheme]].append(entry[args.ipa])

    # For each grapheme, raise:
    #   - a warning if there are duplicate entries
    #   - an error if there are inconsistencies
    #   - an error if the mapping has invalid BIPA
    for grapheme in mapping:
        # check mapping consistency
        if len(mapping[grapheme]) >= 2:
            if len(set(mapping[grapheme])) == 1:
                logger.warning(
                    "Duplicate (redundant) entry or entries for grapheme [%s].",
                    grapheme,
                )
            else:
                logger.error(
                    "Inconsistency for grapheme [%s]: potential mappings %s.",
                    grapheme,
                    str(mapping[grapheme]),
                )

        # check BIPA consistency
        for value in mapping[grapheme]:
            # Get all potential BIPA, skipping over NULLs
            segments = value.split()
            segments = [
                segment.split("/")[1] if "/" in segment else segment
                for segment in segments
            ]
            segments = [
                segment for segment in segments if segment != "NULL" and segment
            ]

            # check for unknown sounds
            unknown = [
                isinstance(clts.bipa[segment], pyclts.models.UnknownSound)
                for segment in segments
            ]
            if any(unknown):
                logger.error(
                    "Mapping [%s] (%s) -> [%s] (%s) includes at least one unknown sound.",
                    grapheme,
                    unicode2codepointstr(grapheme),
                    value,
                    unicode2codepointstr(value),
                )


def trim_profile(profile, clts, args):
    # Make a copy of the profile (so we don't change in place) and clear
    # all frequencies
    new_profile = []
    for entry in profile:
        new_entry = entry.copy()
        new_entry["FREQUENCY"] = 0
        new_entry["EXAMPLES"] = []
        new_profile.append(new_entry)

    # build segment map
    segment_map = {entry[args.grapheme]: entry for entry in new_profile}

    # Collect all keys, so that we will gradually remove them; those with
    # ^ and $ go first
    graphemes = list(segment_map.keys())
    bound_graphemes = [
        grapheme
        for grapheme in graphemes
        if grapheme[0] == "^" and grapheme[-1] == "$"
    ]
    bound_graphemes += [
        grapheme
        for grapheme in graphemes
        if grapheme[0] == "^" and grapheme[-1] == "$"
    ]
    bound_graphemes += [
        grapheme
        for grapheme in graphemes
        if grapheme[0] != "^" and grapheme[-1] == "$"
    ]

    check_graphemes = bound_graphemes + sorted(
        [
            grapheme
            for grapheme in bound_graphemes
            if len(grapheme) > 1 and grapheme not in bound_graphemes
        ],
        key=len,
        reverse=True,
    )

    # For each entry, we will remove it from `segment_map`, apply the resulting
    # profile, and add the entry back at the end of loop (still expansive, but
    # orders of magnitude less expansive than making a copy at each iteration)
    removed = 0
    for grapheme in check_graphemes:
        # Remove the current entry from the segment map, skipping if already
        # removed
        if grapheme not in segment_map:
            continue
        entry = segment_map.pop(grapheme)
        ipa = entry[args.ipa]

        # Obtain the segments without the current rule
        segments = " ".join(apply_profile_to_form(grapheme, segment_map, args))

        # If the resulting `segments` match the `ipa` reference, don't add the
        # rule back (but keep track of how many were removed)
        if ipa == segments:
            logging.info(
                "Rule for grapheme [%s] (%s) is superfluous, removing it...",
                grapheme,
                unicode2codepointstr(grapheme),
            )
            removed += 1
        else:
            # Add the entry back to segment_map
            segment_map[grapheme] = entry

    # Drop from `new_profile` everything that is not in `segment_map` anymore
    new_profile = [
        entry for entry in new_profile if entry[args.grapheme] in segment_map
    ]

    return new_profile, removed


def clean_profile(profile, clts, args):
    """
    Replace user-provided IPA graphemes with the CLTS/BIPA default ones.
    """

    def clean_segment(segment, clts):
        if "/" in segment:
            left, right = segment.split("/")
            return "%s/%s" % (left, str(clts.bipa[right]))
        else:
            return str(clts.bipa[segment])

    # We make and return a copy of the profile, following the best practice
    # of not changing the data structure provided by the user
    new_profile = []
    for entry in profile:
        new_entry = entry.copy()

        # Remove any multiple spaces, split IPA first into segments and then
        # left- and right- slash information (if any), and use the default
        ipa_value = re.sub(r"\s+", " ", new_entry[args.ipa]).strip()
        new_entry[args.ipa] = " ".join(
            [clean_segment(segment, clts) for segment in ipa_value.split()]
        )

        # Add/override the 'UNICODE' field
        new_entry["CODEPOINTS"] = unicode2codepointstr(new_entry[args.grapheme])

        new_profile.append(new_entry)

    return new_profile


def sort_profile(profile, args):
    """
    Return a sorted copy of a profile (suitable for diffs).
    """

    # NULLs are always placed at the top (with special symbols "^" and "$"
    # first), followed by full forms
    # The general sort is first by length, then alphabetically

    sorted_prf = sorted(
        profile,
        key=lambda e: (
            e[args.grapheme] not in ["^", "$"],
            e[args.grapheme] != "^",
            e[args.ipa] != "NULL",
            re.match("\^.*\$", e[args.grapheme]) is None,
            len(e[args.grapheme]),
            e[args.grapheme],
        ),
    )

    return sorted_prf


# TODO: this is changing `segment_map` in place, improve
def apply_profile_to_form(form, language, segment_map, args):
    # Read and prepare form
    if not args.nonfc:
        form = normalize(form)
    if not args.nonfc:
        form = "^%s$" % form

    # apply profile to the form
    i = 0
    segments = []
    while True:
        match = False
        for length in range(len(form[i:]), 0, -1):
            needle = form[i : i + length]
            if needle in segment_map:
                if args.debug_wl:
                    segments.append(
                        "{%s}/{%s}" % (needle, segment_map[needle][args.ipa])
                    )
                else:
                    segments.append(segment_map[needle][args.ipa])

                # Update frequency and examples
                segment_map[needle]["FREQUENCY"] += 1
                segment_map[needle]["EXAMPLES"].append(form)
                segment_map[needle]["LANGUAGES"].append(language)
                i += length
                match = True
                break

        if not match:
            if form[i] == " ":
                if args.debug_wl:
                    segments.append("{ }/{#}")
                else:
                    segments.append("#")
            elif form[i] in ["^", "$"]:
                if args.debug_wl:
                    segments.append("{%s}/{}" % form[i])
            else:
                segments.append("<<%s>>" % form[i])
            i += 1

        if i == len(form):
            break

    # remove nulls; note that this will keep NULLs in debug output,
    # showing what we are skipping over
    segments = [seg for seg in segments if seg != "NULL"]

    return segments


# TODO: use the segments library? we need to collect frequencies...
# TODO: add debug mode
def apply_profile(profile, args):
    """
    Applies a profile to a wordlist, returning new profile counts and segments.

    The segments can be returned in debug mode, to highlight which entry
    is being used.
    """

    # buffer for the debug wordlist
    dwl_buffer = ""

    # Make a copy of the profile (so we don't change in place) and clear
    # all frequencies
    new_profile = []
    for entry in profile:
        new_entry = entry.copy()
        new_entry["FREQUENCY"] = 0
        new_entry["EXAMPLES"] = []
        new_entry["LANGUAGES"] = []
        new_entry["TYPES"] = None
        new_entry["SCA"] = None
        new_profile.append(new_entry)

    # Use the specified delimiter
    if args.csv:
        delimiter = ","
    else:
        delimiter = "\t"

    # If a multilanguage checking was requested (for different profiles,
    # such as in the case of WOLD), cache the language_id from the
    # profile name; [:-4] if for the default `.tsv` suffix
    if args.multilang:
        lang_id = pathlib.PurePosixPath(args.profile).name[:-4]

    # Build segment map, load the forms, and do the segmentation
    segment_map = {entry[args.grapheme]: entry for entry in new_profile}
    with open(args.wl) as wordlist:
        reader = csv.DictReader(wordlist, delimiter=delimiter)

        # add header to buffer, if output was requested
        if args.debug_wl:
            dwl_buffer = "%s\n" % delimiter.join(reader.fieldnames)

        # iterate over rows
        for row in reader:
            # Skip if multiple language verification is requested and
            # language id does not match
            if args.multilang:
                if row[args.lang_id] != lang_id:
                    continue

            # Run the segmentation, carrying information on language ID
            # as well
            segments = apply_profile_to_form(
                row[args.form], row[args.lang_id], segment_map, args
            )

            # Collect output, if requested
            if args.debug_wl:
                row["Segments"] = " ".join(segments)
                dwl_buffer += "%s\n" % delimiter.join(
                    [row[field] for field in reader.fieldnames]
                )

    # output debug wordlist if requested
    if args.debug_wl:
        with open(args.debug_wl, "w") as handler:
            handler.write(dwl_buffer)

    # Compile/fix remaining fields, such as frequency values (making sure
    # they are all strings and getting some random but reproducible subset),
    # building a list of languages, building sound class representations,
    # etc.
    for entry in new_profile:
        entry["FREQUENCY"] = str(entry["FREQUENCY"])

        # Get a set of the examples, sample it, remove boundaries if
        # necessary, and join in a single sorted string
        # Note that we seed with the Grapheme, so it is reproducible
        examples = set(entry["EXAMPLES"])
        random.seed(entry[args.grapheme])
        example_sample = random.sample(examples, min(len(examples), 3))
        if not args.nobound:
            example_sample = [form[1:-1] for form in example_sample]

        example_sample = (
            ",".join(sorted(example_sample)).replace("\n", " ").strip()
        )

        entry["EXAMPLES"] = '"%s"' % example_sample

        # Get a sorted set of the languages
        entry["LANGUAGES"] = ",".join(sorted(set(entry["LANGUAGES"])))

    return new_profile


def output_profile(profile, clts, args):
    """
    Writes a profile to disk or to screen, using a default column order.
    """

    # Collect the fields used over the entire profile
    prf_fields = set(
        list(
            itertools.chain.from_iterable(
                [list(entry.keys()) for entry in profile]
            )
        )
    )

    # From the list of default columns, build an output list (provided that the
    # field is found somewhere) and remove it from the `fields` we just collected
    output_fields = [
        field
        for field in [
            args.grapheme,
            args.ipa,
            "SCA",
            "TYPES",
            "FREQUENCY",
            "CODEPOINTS",
        ]
        if field in prf_fields
    ]
    output_fields += sorted(
        [field for field in prf_fields if field not in output_fields]
    )

    # Add headers to buffer
    buffer = "%s\n" % "\t".join(output_fields)

    # Fill buffer with entries; as the `csv` library might have returned empty fields
    # as `None`, we need to check for those
    for entry in profile:
        if entry["FREQUENCY"] == "0" and not args.keepzero:
            continue

        # For special symbols "^" and "$", the EXAMPLES column will be
        # empty (if it exists)
        if "EXAMPLES" in entry:
            if entry[args.grapheme] in ["^", "$"]:
                entry["EXAMPLES"] = ""

        # Map a grapheme column to a CLTS type column, overriding any
        # previous information
        entry["TYPES"] = ipa2types(entry[args.ipa], clts)
        entry["SCA"] = ipa2sca(entry[args.ipa], clts)

        # build line representation and extend buffer
        tmp = [entry.get(field, "") for field in output_fields]
        tmp = [value if value else "" for value in tmp]
        buffer += "%s\n" % "\t".join(tmp)

    # Output
    if not args.output:
        print(buffer)
    else:
        with open(args.output, "w") as handler:
            handler.write(buffer)


def main(args):
    """
    Entry point.
    """

    # Load CLTS
    # TODO: use default repos path
    clts = CLTS(pathlib.Path(args.clts).expanduser().as_posix())

    # Load the profile
    profile = read_profile(args.profile, args)

    if args.command == "format":
        logging.info("Cleaning profile...")
        profile = clean_profile(profile, clts, args)

        # Apply profile, collecting frequencies, if a wordlist was specified
        if args.wl:
            profile = apply_profile(profile, args)

        logging.info("Sorting profile...")
        profile = sort_profile(profile, args)
    elif args.command == "trim":
        logging.info("Trimming profile...")

        # Run the trimmer as many times as necessary until nothing more is left
        # to remove
        total_removed = 0
        while True:
            profile, removed = trim_profile(profile, clts, args)
            total_removed += removed
            if removed == 0:
                break

        logging.info("%i superfluous rules were removed.", total_removed)

        # Apply profile, collecting frequencies, if a wordlist was specified
        if args.wl:
            profile = apply_profile(profile, args)

    check_consistency(profile, clts, args)

    # Export
    output_profile(profile, clts, args)


if __name__ == "__main__":
    # setup logger
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Define the parser for when called from the command-line
    parser = argparse.ArgumentParser(
        description="Orthographic profile formatter/linter."
    )
    parser.add_argument(
        "command",
        type=str,
        help="The action to be performed on an orthographic profile.",
        choices=["format", "trim"],
    )
    parser.add_argument(
        "profile",
        type=str,
        help="Path to the orthographic profile to be manipulated.",
    )
    parser.add_argument(
        "--wl",
        type=str,
        help="Path to the relative wordlist to be used for frequency and analysis.",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Path to the output orthographic profile. If not provided, it will be printed to screen.",
        default="",
    )
    parser.add_argument(
        "--debug_wl",
        type=str,
        help="Path to the output debug wordlist, if any",
        default="",
    )
    parser.add_argument(
        "--grapheme",
        type=str,
        help="Name of the grapheme column (default: `Grapheme`).",
        default="Grapheme",
    )
    parser.add_argument(
        "--ipa",
        type=str,
        help="Name of the IPA column (default: `IPA`).",
        default="IPA",
    )
    parser.add_argument(
        "--clts",
        type=str,
        help="Path to the CLTS data repos (default: `~/.config/cldf/clts`).",
        default="~/.config/cldf/clts",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Uses commas as separators in the wordlist (default: tabs)",
    )
    parser.add_argument(
        "--form",
        type=str,
        help="Name of the form column in the wordlist (default: `Form`)",
        default="Form",
    )
    parser.add_argument(
        "--lang_id",
        type=str,
        help="Name of the language id column in the wordlist (default: `Language_ID`)",
        default="Language_ID",
    )
    parser.add_argument(
        "--multilang",
        action="store_true",
        help="Instruct to use multiple profiles, checking the language id.",
    )
    parser.add_argument(
        "--nonfc",
        action="store_true",
        help="Instruct not to perform Unicode NFC normalization in profile and forms.",
    )
    parser.add_argument(
        "--keepzero",
        action="store_true",
        help="Instruct to keep entries with zero frequency in output.",
    )
    parser.add_argument(
        "--nobound",
        action="store_true",
        help="Instruct not to incorporate automatic boundary symbols to forms.",
    )
    ARGS = parser.parse_args()

    main(ARGS)
