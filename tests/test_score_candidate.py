# Esegui da python nella root del progetto
import sys; sys.path.insert(0, ".")
from core.source_resolver.query import score_candidate

class FakeTrack:
    def __init__(self, title, artist=""):
        self.title = title
        self.artist = artist

# Deve dare score alto
print(score_candidate("shakira waka waka", FakeTrack("Waka Waka (This Time for Africa)", "Shakira")))

# Deve dare score basso (penalità cover)
print(score_candidate("shakira waka waka", FakeTrack("Waka Waka COVER karaoke")))

# Deve dare score basso (penalità lyrics)
print(score_candidate("bohemian rhapsody", FakeTrack("Bohemian Rhapsody Lyrics Video")))

# Lyrics query esplicita → nessuna penalità
print(score_candidate("bohemian rhapsody lyrics", FakeTrack("Bohemian Rhapsody Lyrics Video")))