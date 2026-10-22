"""The editable texts of each storefront page: key, admin label, the text
shown until staff change it, max length and whether line breaks are kept.
The defaults match what the page's HTML shows before the API answers."""

CONCEPT = [
    ('hero_eyebrow',      'Top line',                    'Σenario / The Story', 100, False),
    ('hero_title',        'Headline',                    'A new form of luxury.\nNot built on status.', 200, True),
    ('hero_title_accent', 'Headline — orange part',      'Built on reality.', 100, False),
    ('hero_body',         'Story text',
        'Σenario is a shift in perception. We find beauty where others see waste. '
        'Silence where others see emptiness. Structure inside chaos.\n\n'
        'Industrial spaces. Rust. Movement. Human truth.\n'
        'Not imperfections. Evidence.\n\n'
        'Every piece reflects observation.\n'
        'Minimal, precise, intentional.\n'
        'No noise. No performance. No excess.\n'
        'Just identity.\n\n'
        'Luxury is no longer about showing more.\n'
        "It's about seeing more.", 3000, True),
    ('hero_closing',      'Story — orange closing line', 'Σenario is a mindset.', 200, False),
    ('process_title',     'Process — title',             'The Process', 100, False),
    ('process_subtitle',  'Process — subtitle',          'Where the clothes come from', 150, False),
    ('process_1',         'Process — photo 1 label',     '01 — Observation', 80, False),
    ('process_2',         'Process — photo 2 label',     '02 — Movement', 80, False),
    ('process_3',         'Process — photo 3 label',     '03 — Craft', 80, False),
    ('process_4',         'Process — photo 4 label',     '04 — Contrast', 80, False),
    ('quote',             'Black quote block',           'Wear\nthe\nScript.', 200, True),
    ('quote_attr',        'Black quote — small line',    'Σenario / Brand Manifesto', 100, False),
    ('pillars_title',     'Brand — section title',       'The Brand', 100, False),
    ('pillar_1_num',      'Brand 1 — small line',        '01 — The Idea', 80, False),
    ('pillar_1_title',    'Brand 1 — title',             'Born from Raw Reality', 120, False),
    ('pillar_1_body',     'Brand 1 — text',
        'Σenario did not start in a studio. It started in the street — industrial zones, '
        'waste environments, real human moments most brands filter out. Trash, rust, '
        'and texture are not imperfections. They are evidence of a life actually lived.', 1000, True),
    ('pillar_2_num',      'Brand 2 — small line',        '02 — The Purpose', 80, False),
    ('pillar_2_title',    'Brand 2 — title',             'Real People. No Models.', 120, False),
    ('pillar_2_body',     'Brand 2 — text',
        'Every piece is designed to be worn by the person who builds things and moves '
        'through cities without performance. We shoot the people around us — friends, '
        'workers, anyone who carries themselves with quiet presence.', 1000, True),
    ('pillar_3_num',      'Brand 3 — small line',        '03 — The Identity', 80, False),
    ('pillar_3_title',    'Brand 3 — title',             'The Σ Symbol', 120, False),
    ('pillar_3_body',     'Brand 3 — text',
        'In mathematics, sigma represents a sum — the total of all parts. Every garment '
        'is the sum of the environment it came from, the person who will wear it, '
        'and the moment it was made for. Nothing added that should not be there.', 1000, True),
]

PAGES = {'concept': CONCEPT}


# The replaceable photos of each storefront page: key, admin label. Until
# staff upload one, the page keeps the photo built into its HTML.
CONCEPT_IMAGES = [
    ('process_photo_1', 'Process — photo 1'),
    ('process_photo_2', 'Process — photo 2'),
    ('process_photo_3', 'Process — photo 3'),
    ('process_photo_4', 'Process — photo 4'),
]

PAGE_IMAGES = {'concept': CONCEPT_IMAGES}
