"""
Support for working with the OpenNLP format and PoolParty.
"""

import os
from os.path import join as joinpath
from glob import iglob
from pp_api import ppextract2matches, remove_overlaps

from extract_concepts import clean_input  # extract_concepts depends on pp_api


# Just raise an AssertionError for now
class OpenNLPError(AssertionError):
    pass


def apply_edits(text, edits):
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

    :return: string
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

        content = text[start:end]
        if match and content.replace("\n", " ").lower() != match:
            print("Expected:"+match)
            print("Found:"+content)
            end -= 1  # set back to what was in the input
            raise OpenNLPError('Span {start}..{end} is not the string "{match}"!'.format(**locals()))

        output.append(text[offset:start])   # Untagged text
        output.append("<START:%s>%s<END>" % (tag, content))
        offset = end

    output.append(text[offset:])
    return ''.join(output)


def process_folder(worker, tag, inpath, outpath, fileglob="**", encoding="utf8", progress=False):
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
    :param encoding: File encoding for input and output.
    :param progress: Print a dot after processing each file, as a progress indicator
    :return:
    """

    os.makedirs(outpath, exist_ok=True)
    if not os.path.isdir(inpath):  # Trigger an error
        os.listdir(inpath)

    for fname in iglob(joinpath(inpath, fileglob), recursive=True):
        if not os.path.isfile(fname):
            continue

        # Get the text
        with open(fname, encoding=encoding) as fp:
            text = fp.read()

        text = clean_input(text)  # Clean to match the offsets returned by the extractor

        # Run it through the extractor
        concepts = worker(text)
        # restructure the results and insert as OpenNLP annotations
        edits = ppextract2matches(concepts, tag=tag, overlaps=False)
        annotated = apply_edits(text, edits)

        # Write out in result folder
        outfile = joinpath(outpath, fname)
        os.makedirs(os.path.dirname(outfile), exist_ok=True)
        with open(outfile, "w", encoding=encoding) as fpout:
            fpout.write(annotated)

        if progress:
            print(".", end="")

    if progress:
        print()
