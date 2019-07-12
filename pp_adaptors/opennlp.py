"""
Support for working with the OpenNLP format and PoolParty.
"""

import os
from os.path import basename, join as joinpath
import sys
from glob import iglob
from itertools import zip_longest
import re

from pp_api import ppextract2matches, remove_overlaps

from extract_concepts import clean_input  # extract_concepts depends on pp_api


# Just raise an AssertionError for now
class OpenNLPError(AssertionError):
    pass

# def _rewrap(source, width=80):
#     # This wrapper is not GUARANTEED to preserve length and positions...
#
#     wrapper = textwrap.TextWrapper(break_long_words=False,
#                                    break_on_hyphens=False,
#                                    replace_whitespace=False,
#                                    drop_whitespace=False,
#                                    width=width)
#
#     return "\n".join(wrapper.fill(line).replace(" \n", "\n").replace("\n ", "\n") for line in source)


def wraplines(text, width=80):
    """
    Wrap text, respecting existing newlines and character offsets.
    Only known to be valid with 1-byte newlines (i.e. Unix-style LF, not CR-LF)
    Tabs are not expected to occur, and will be converted to a single space if they do.
    """

    lines = text.replace("\t", " ").split("\n")
    new = []
    for line in lines:
        # Special-case empty lines
        if not line:
            new.append(line)
            continue

        # While the line should and can be broken:
        while len(line) > width and " " in line:
            # Wrap at the rightmost available space
            cut = line.rfind(" ", 0, width)
            if cut == -1:
                # else just wrap at the first opportunity
                cut = line.find(" ")

            # We KNOW there was a space, so `cut` is set
            new.append(line[:cut])
            line = line[cut+1:]

        # Any remaining content cannot or should not be broken: Ship it whole
        # (But not if the last wrap left nothing behind)
        if line:
            new.append(line)

    return "\n".join(new)


def longlines(text, collapse=False):
    """
    Remove newlines to turn each paragraph into a single logical line, as
    needed for sentence recognition (and also expected in many text editors).
    Attempt to preserve significant line breaks, i.e., between paragraphs or
    in displays.

    A paragraph boundary consists of two or more newlines (with whitespace
    allowed between and after them), or of a newline followed by indentation.
    Line-final whitespace does not affect the algorithm and is not included as
    part of the boundary.

    This will miss paragraphs with all lines indented; but that's
    necessary, because this formatting can also indicate lists (and in
    wikipedia pages, it usually does.)

    Trying for full generality: Runs of spaces are not collapsed unless the
    `collapse` flag is true. Surrounding whitespace is not removed. The default
    should preserve the length and offsets of the input.

    :param text: string
    :param collapse: If true, runs of spaces and newlines are simplified.
    :return:
    """

    return "".join(_iterlonglines(text, collapse))


def _iterlonglines(text, collapse=False):
    """
    Implement logic of removing newlines to turn each paragraph into a single line.
    Returns an iterator
    :param text:
    :param collapse:
    :return:
    """
    chunks = iter(re.split(r"(\n\s*\n[ \t]*|\n[ \t]+)", text))
    for line in chunks:
        # Unfold
        oneline = line.replace("\n", " ")
        # Collapse internal whitespace (if requested)
        if collapse:
            oneline = re.sub(r"\s+", " ", oneline.strip())
        yield oneline

        linebreak = next(chunks)
        # print("Line:", line, "\nBreak:", repr(linebreak))
        yield "\n" if collapse else linebreak




# The set of printable ascii characters
_asciirange = set(chr(n) for n in range(ord(" "), ord("~")+1))


def ascii_equal(left, right):
    """
    Compare two strings, one of which may have been dumbed down to ascii or
    near-ascii. Space is included but newline is not, so the two can be freely
    (mis)matched.
    """

    # If a printable ascii character is paired to a non-ascii, just skip over.
    # Else compare (case-insensitive)
    tr_map = "".maketrans("\xa0ABCDEFGHIJKLMNOPQRSTUVWXYZ", " abcdefghijklmnopqrstuvwxyz")

    paired = zip_longest(left.translate(tr_map), right.translate(tr_map))
    return not any((c1 in _asciirange) == (c2 in _asciirange) and c1 != c2
                    for c1, c2 in paired)


def apply_edits(text, edits, endtag=" <END> "):
    """
    Annotate `text` in the OpenAPI style. `edits` is a list of 4-tuples
    describing the annotations.
    Each 4-tuple specifies a span to be annotated and the tag to apply.
    If `match` is non-empty, ensure that the content of span matches the
    string `match`.

    Only non-overlapping Edit spans must be non-overlapping and increasing. Others will be discarded.

    :param text:
    :param edits: list of 4-tuples (start, end, tag, content):
            start: Index of the first character in the span to annotate
            end:   Index of the last character in the span -- NOT a Python range!
            tag:   The tag to annotate with
            content: the text of the matched region, or None to suppress checking
    :param endtag: string

    :return: the input text with inline annotations
    """

    edits = remove_overlaps(edits)

    offset = 0
    output = []
    for start, end, tag, match in edits:
        if start < offset:
            # Edit spans must be non-overlapping and increasing
            raise OpenNLPError('Span {start}..{end} overlaps with previous spans!'.format(**locals()))
        if end >= len(text):
            maxlen = len(text)
            raise OpenNLPError(
                'Span {start}..{end} extends past the end of the input (length {maxlen})!'.format(**locals()))

        end += 1      # Convert to a Python range end
        tag = " "+tag.strip()+" "

        content = text[start:end]
        if match and not ascii_equal(content.replace("\n", " "), match):
            print("Expected:"+match)
            print("Found:"+content)
            end -= 1  # set back to what was in the input
            raise OpenNLPError('Span {start}..{end} is "{content}", expected "{match}"!'.format(**locals()))

        output.append(text[offset:start])   # Untagged text
        output.append(tag+content+endtag)   # Tagged text span
        offset = end

    output.append(text[offset:])
    return ''.join(output)


def process_folder(worker, tag, inpath, outpath, fileglob="**", *, plaintext=False, encoding="utf8", progress=False):
    """
    Create an annotated corpus in OpenNLP syntax from all files in the
    folder `inpath`, or subfolders, that match the pattern `fileglob`
    (interpreted as a recursive glob). E.g., use fileglob="**/*.txt" to
    recursively match all files with the suffix .txt.

    Each file is run through the extractor and annotated in the OpenNLP format,
    with the annotation `tag` wherever a concept was detected.

    :param inpath: The folder to annotate.
    :param outpath: Where to write annotated files. Will be created if needed.
    :param worker: Annotation function (e.g., as returned by extractor_worker()
    :param tag: The annotation label to add.
    :param fileglob: Pattern for which files in `inpath` to annotate.
    :param plaintext: True if only text files will be processed (allows text format to be preserved)
    :param encoding: File encoding for input (if plaintext) and output.
    :param progress: Print a dot after processing each file, as a progress indicator
    :return:
    """

    if not os.path.isdir(inpath):  # Trigger an error
        os.listdir(inpath)

    # Normalize to _not_ ending a directory path with a slash
    if inpath.endswith(os.path.sep) and len(inpath) > 1:
        inpath = inpath[:-1]

    for fname in iglob(joinpath(inpath, fileglob), recursive=True):
        if not os.path.isfile(fname):
            continue

        # Destination in result folder
        # We can't use `basename` since the file might be in a subdirectory
        samepath = fname[len(inpath)+1:] + ".onlp"
        outfile = joinpath(outpath, samepath)

        try:
            annotated = process_file(worker, tag, fname, plaintext, encoding)
        except (OpenNLPError, TypeError) as error:
            # A TypeError could be due to an extractor timeout,
            # which is swallowed but causes the worker to return None
            print("In file {}:\n".format(fname), error, file=sys.stderr)
            print("SKIPPING...\n", file=sys.stderr)
            continue


        os.makedirs(os.path.dirname(outfile), exist_ok=True)
        with open(outfile, "w", encoding=encoding) as fpout:
            fpout.write(annotated)

        if progress:
            print(".", end="", flush=True)

    if progress:
        print()



def diagnose(left, right):
    """Find and inspect the mismatch"""

    from itertools import zip_longest

    mismatches = [ (n, a, b) for n, (a,b)
                   in enumerate(zip_longest(left, right, fillvalue="")) if not ascii_equal(a, b) ]

    n, a, b = mismatches[0]
    print("MISMATCH:", n, repr(a), repr(b))
    offset = max(n-3, 0)
    print("Left:", repr(left[offset:offset+28]))
    print("Rite:", repr(right[offset:offset+28]))
    sys.stdout.flush()


tr_map = "".maketrans("\n\xa0ABCDEFGHIJKLMNOPQRSTUVWXYZ", "  abcdefghijklmnopqrstuvwxyz")

def loose_match(left, right):
    """
    Compare the strings, allowing for case-folding and lost non-breaking spaces or newlines
    :param left:
    :param right:
    :return:
    """

    paired = zip_longest(left.translate(tr_map), right.translate(tr_map), fillvalue="")
    return not any(c1 != c2 for c1, c2 in paired)


def ascii_equal(left, right):
        """
        Compare two strings, one of which may have been dumbed down to ascii or
        near-ascii. Space is included but newline is not, so the two can be freely
        (mis)matched.
        """

        # If a printable ascii character is paired to a non-ascii, just skip over.
        # Else compare (case-insensitive)
        tr_map = "".maketrans("\xa0ABCDEFGHIJKLMNOPQRSTUVWXYZ", " abcdefghijklmnopqrstuvwxyz")

        paired = zip_longest(left.translate(tr_map), right.translate(tr_map), fillvalue="")
        return not any((c1 in _asciirange) == (c2 in _asciirange) and c1 != c2
                       for c1, c2 in paired)


def process_file(worker, tag, fname, plaintext=False, encoding="utf8"):
    """
    Run a document through the extractor and store the annotated text

    :param worker: Extractor callable that takes a single argument, `filename`
    :param tag: Tag to apply to all matched concepts
    :param fname: Filename of a document to read or upload for extraction
    :param plaintext:
    :param encoding:
    :return:
    """

    # For plaintext files, preserve linebreaks if we can
    if plaintext:
        with open(fname, encoding=encoding) as fp:
            data = fp.read()
        cleaned = clean_input(data)  # Match the extractor offsets, keeping newlines

        # Run it through the extractor
        # Protect from extractor character set bug: Sprinkle some unicode
        clean_utf = cleaned.replace(" ", "\xa0", 1)
        concepts, base_text = worker(clean_utf)

        # Substitute our own version of the text, if equivalent
        #-- if ascii_equal(base_text.lower(), cleaned.lower().replace("\n", " ")):
        if loose_match(base_text, cleaned):
            base_text = cleaned
        else:
            print("\n{fname}: Cannot match extractor text with original (dropping newlines)".format(fname=fname))
            diagnose(base_text, cleaned)
    else:
        concepts, base_text = worker(fname)

    # restructure the results and insert as OpenNLP annotations
    edits = ppextract2matches(concepts, tag=tag, overlaps=False)
    annotated = apply_edits(base_text, edits)

    return annotated
