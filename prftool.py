#!/usr/bin/env python3

# TODO: remove zero frequency

# Import Python default libraries
import argparse
import csv
from collections import defaultdict
import itertools
import logging
from pathlib import Path
import re
import unicodedata

# Import other libraries
import pyclts
from pyclts import CLTS

# TODO: Deal with multiple IPA columns/languages


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
            segments = [segment for segment in segments if segment != "NULL"]

            # check for unknown sounds
            unknown = [
                isinstance(clts.bipa[segment], pyclts.models.UnknownSound)
                for segment in segments
            ]
            if any(unknown):
                logger.error(
                    "Mapping [%s] -> [%s] includes at least one unknown sound.",
                    grapheme,
                    value,
                )


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

    # NULLs are always placed at the top, followed by full forms
    # The general sort is first by length, then alphabetically

    sorted_prf = sorted(
        profile,
        key=lambda e: (
            e[args.ipa] != "NULL",
            re.match("\^.*\$", e[args.grapheme]) is None,
            len(e[args.grapheme]),
            e[args.grapheme],
        ),
    )

    return sorted_prf


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
        new_profile.append(new_entry)

    # Do the segmentation
    segment_map = {entry[args.grapheme]: entry for entry in new_profile}

    # Use the specified delimiter
    if args.csv:
        delimiter = ","
    else:
        delimiter = "\t"

    # Load the forms
    with open(args.wl) as wordlist:
        reader = csv.DictReader(wordlist, delimiter=delimiter)

        # add header to buffer, if output was requested
        if args.debug_wl:
            dwl_buffer = "%s\n" % delimiter.join(reader.fieldnames)

        # iterate over rows
        for row in reader:
            # Read and prepare form
            form = row[args.form]
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
                                "{%s}/{%s}"
                                % (needle, segment_map[needle][args.ipa])
                            )
                        else:
                            segments.append(segment_map[needle][args.ipa])
                        segment_map[needle]["FREQUENCY"] += 1
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

            # print(form, segments)
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

    # Make sure all frequency values are strings
    for entry in new_profile:
        entry["FREQUENCY"] = str(entry["FREQUENCY"])

    return new_profile


def output_profile(profile, args):
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
        for field in [args.grapheme, args.ipa, "FREQUENCY", "CODEPOINTS"]
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
    clts = CLTS(Path(args.clts).expanduser().as_posix())

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

    check_consistency(profile, clts, args)

    # Export
    output_profile(profile, args)


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
        choices=["format"],
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
        "--nonfc",
        action="store_true",
        help="Instruct not to perform Unicode NFC normalization in profile and forms.",
    )
    parser.add_argument(
        "--nobound",
        action="store_true",
        help="Instruct not to incorporate automatic boundary symbols to forms.",
    )
    ARGS = parser.parse_args()

    main(ARGS)