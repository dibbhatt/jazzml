############################################################################
# pipeline.py                                                              #
# Name: Evan Chow                                                          #
# Execution: $ python pipeline.py                                          #
# Description: A client Python program to implement the entire pipeline    #
# (as a demo) from MIDI parsing to music generation, calling the other     #
# modules in the neighboring directories.                                  #
# Data: Pat Metheny MIDI file, w/well-separated melody/accompaniment.      #
#                                                                          #
############################################################################

# Tip for development: write each part in this client program first, then
# move the code to its own module later. That way, you don't have to deal
# with any messy "can't find that var since in another module's
# function" problems, which may slow you down.

# Try to keep your section dividers to one line (""" ... """).

# Defines
head = lambda x: x[0:5] # from R
tail = lambda x: x[:-6:-1] # from R
ppf = lambda n: "%.3f   %s" % (n.offset, n)

# Imports
from music21 import *
from collections import defaultdict, OrderedDict
from itertools import groupby, izip_longest
import pygame, copy, sys

# My imports
sys.path.append("./extract")
sys.path.append("./grammar")
from grammar import grammar
from findSolo import findSolo

""" Parse the MIDI data for separate melody and accompaniment parts. """

play = lambda x: midi.realtime.StreamPlayer(x).play()
stop = lambda: pygame.mixer.music.stop()

metheny = converter.parse("andtheniknew_metheny.mid")

# Get melody part, compress into single voice.
# For Metheny piece, Melody is Part #5.
melodyStream = metheny[5]
melody1, melody2 = melodyStream.getElementsByClass(stream.Voice)
for j in melody2:
    melody1.insert(j.offset, j)
melodyVoice = melody1

# FOR REFERENCE
# fullMelody.append(key.KeySignature(sharps=1, mode='major'))

# Bad notes: melodyVoice[370, 391]
# the two B-4, B-3 around melodyVoice[362]. I think: #362, #379
# REMEMBER: after delete each of these, 
# badIndices = [370, 391, 362, 379]
# BETTER FIX: iterate through, if length = 0, then bump it up to 0.125
# since I think this is giving the bug.
for i in melodyVoice:
    if i.quarterLength == 0.0:
        i.quarterLength = 0.25

# Change key signature to adhere to compStream (1 sharp, mode = major).
# Also add Electric Guitar.
melodyVoice.insert(0, instrument.ElectricGuitar())
melodyVoice.insert(0, key.KeySignature(sharps=1, mode='major'))

# The accompaniment parts. Take only the best subset of parts from
# the original data. Maybe add more parts, hand-add valid instruments.
# Should add least add a string part (for sparse solos).
# Verified are good parts: 0, 1, 6, 7
partIndices = [0, 1, 6, 7] # TODO: remove 0.0==inf duration bug in part 7
compStream = stream.Voice()
compStream.append([j.flat for i, j in enumerate(metheny) if i in partIndices])

# Full stream containing both the melody and the accompaniment.
# All parts are flattened.
fullStream = stream.Voice()
for i in xrange(len(compStream)):
    fullStream.append(compStream[i])
fullStream.append(melodyVoice)

# Extract solo stream, assuming you know the positions ..ByOffset(i, j).
# Note that for different instruments (with stream.flat), you NEED to use
# stream.Part(), not stream.Voice().
# Accompanied solo is in range [478, 548)
soloStream = stream.Voice()
for part in fullStream:
    newPart = stream.Part()
    newPart.append(part.getElementsByClass(instrument.Instrument))
    newPart.append(part.getElementsByClass(tempo.MetronomeMark))
    newPart.append(part.getElementsByClass(key.KeySignature))
    newPart.append(part.getElementsByClass(meter.TimeSignature))
    newPart.append(part.getElementsByOffset(476, 548, includeEndBoundary=True))
    np = newPart.flat
    soloStream.insert(np)

# MELODY: Group by measure so you can classify. 
# Note that measure 0 is for the time signature, metronome, etc. which have
# an offset of 0.0.
melody = soloStream[-1]
allMeasures = OrderedDict()
offsetTuples = [(int(n.offset / 4), n) for n in melody]
measureNum = 0 # for now, don't use real m. nums (119, 120)
for key, group in groupby(offsetTuples, lambda x: x[0]):
    allMeasures[measureNum] = [n[1] for n in group]
    measureNum += 1

""" Just play the chord accompaniment with the melody. Refine later. """
""" Think I successfully extracted just the chords in chordStream(). """
# Generate the chord structure. Use just track 1 (piano) since it is
# the only instrument that has chords. Later, if you have time, you can
# mod this so it works with any MIDI file.
# Group into 4s, just like before.
chordStream = soloStream[0]
chordStream.removeByClass(note.Rest)
chordStream.removeByClass(note.Note)
allMeasures_chords = OrderedDict()
offsetTuples_chords = [(int(n.offset / 4), n) for n in chordStream]
measureNum = 0
for key, group in groupby(offsetTuples_chords, lambda x: x[0]):
    allMeasures_chords[measureNum] = [n[1] for n in group]
    measureNum += 1


""" Create test measure. Won't work immediately for playback because just a
    list of notes (and no metronome mark indicated). """
# TEST: generate the grammar for the first measure. Need to reconvert it
# into a stream since allMeasures stores LISTS of notes and not the
# actual voices themselves.
# For now, though, leave out append instrument, key signature, etc.
# OUTPUT: create a "cluster" for this test measure.
m1 = stream.Voice()
# for i in allMeasures[0]:
#     m1.append(i)
for i in allMeasures[1]:
    m1.insert(i.offset, i) # insert so consistent offsets with original data

# TEST: Get chords for current measure.
c1 = stream.Voice()
for i in allMeasures_chords[1]:
    c1.insert(i.offset, i) # insert so consistent offsets with original data

for ix, nr in enumerate(m1):
    """ Iterate over the notes and rests in m1, finding the grammar and
        writing it to a string. """

    # First, get the length for each element. e.g. 8th note = R8, but
    # to simplify things you'll use the direct num, e.g. R,0.125
    if (ix == (len(m1)-1)):
        # the gap between current note and next note
        diff = 4.0 - nr.offset
    else:
        diff = m1[ix + 1].offset - nr.offset

    # Next, get type of note, e.g. R for Rest, C for Chord, etc.
    # Dealing with solo notes here. If happen to run into chord by accident,
    # call it "C".
    elementType = ' '
    lastChord = [n for n in c1 if n.offset <= nr.offset][-1]

    """ Watch out for control flow: rearrange later so flows well. """
    # R: First, check if it's a rest. Clearly a rest --> only one possibility.
    if isinstance(nr, note.Rest):
        elementType = 'R'
    # C: Next, check to see if note pitch is in the last chord.
    elif nr.name in lastChord.pitchNames:
        elementType = 'C'
    # L: Check if it's a complementary tone with the last chord.

    # S: Check if it's a scale tone.

    # A: Check if it's an approach tone.

    # X: Otherwise, it's an arbitrary tone.


    print "%s | %s" % (elementType, ppf(nr))
    

    # elif isinstance(nr, )
    """ If is instance of a chord note. Requires: find chord and notes.
        Check the chordStream's measure 1 to find chord. """