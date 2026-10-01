# Held-out slot sheet (80 questions)

Write one question per row, in the mention style given for each company. Nothing else about the question is fixed. The company assignment is pinned by `heldout_template.sha256` and was drawn before any question existed (`evals/HELDOUT_PROTOCOL.md` 3.2).

Mention styles: **brand** = the name people use; **legal** = the registered style (`Apple Inc.`); **ticker** = the symbol; **informal** = a looser form a person might type.

| id | tier | expected | company (stored name) | ticker | name class | mention style |
|---|---|---|---|---|---|---|
| H01 | lookup | ANSWER | NiSource | NI | plain | **legal** |
| H02 | lookup | ANSWER | Trade Desk (The) | TTD | inverted_the | **legal** |
| H03 | lookup | ANSWER | Jack Henry & Associates | JKHY | punctuated | **legal** |
| H04 | lookup | ANSWER | Fox Corporation (Class A) | FOXA | share_class | **ticker** |
| H05 | lookup | ANSWER | Darden Restaurants | DRI | multi_word | **ticker** |
| H06 | lookup | ANSWER | Oneok | OKE | plain | **informal** |
| H07 | lookup | ANSWER_WITH_ASSUMPTION | J.M. Smucker Company (The) | SJM | inverted_the | **legal** |
| H08 | lookup | ANSWER_WITH_ASSUMPTION | AT&T | T | punctuated | **informal** |
| H09 | lookup | ANSWER_WITH_ASSUMPTION | News Corp (Class A) | NWSA | share_class | **informal** |
| H10 | aggregation | ANSWER | *(no company)* | | | |
| H11 | aggregation | ANSWER | *(no company)* | | | |
| H12 | aggregation | ANSWER | *(no company)* | | | |
| H13 | aggregation | ANSWER | *(no company)* | | | |
| H14 | aggregation | ANSWER | Monster Beverage | MNST | multi_word | **brand** |
| H15 | aggregation | ANSWER | *(no company)* | | | |
| H16 | aggregation | ANSWER | *(no company)* | | | |
| H17 | aggregation | ANSWER | *(no company)* | | | |
| H18 | raw_facts | ANSWER | Medtronic | MDT | plain | **informal** |
| H19 | raw_facts | ANSWER | Walt Disney Company (The) | DIS | inverted_the | **legal** |
| H20 | raw_facts | ANSWER | Procter & Gamble | PG | punctuated | **informal** |
| H21 | raw_facts | ANSWER | Global Payments | GPN | multi_word | **informal** |
| H22 | raw_facts | ANSWER | Veralto | VLTO | plain | **legal** |
| H23 | raw_facts | ANSWER_WITH_ASSUMPTION | Hartford (The) | HIG | inverted_the | **informal** |
| H24 | raw_facts | ANSWER_WITH_ASSUMPTION | Bio-Techne | TECH | punctuated | **ticker** |
| H25 | time | ANSWER | Agilent Technologies | A | multi_word | **brand** |
| H26 | time | ANSWER | Autodesk | ADSK | plain | **ticker** |
| H27 | time | ANSWER | Hershey Company (The) | HSY | inverted_the | **informal** |
| H28 | time | ANSWER | Take-Two Interactive | TTWO | punctuated | **ticker** |
| H29 | time | ANSWER | GE HealthCare | GEHC | multi_word | **informal** |
| | | | Evergy | EVRG | plain | **ticker** |
| H30 | time | ABSTAIN | Estée Lauder Companies (The) | EL | inverted_the | **brand** |
| H31 | time | ABSTAIN | Snap-on | SNA | punctuated | **ticker** |
| H32 | time | ABSTAIN | Synchrony Financial | SYF | multi_word | **brand** |
| H33 | ratio | ANSWER | Intuit | INTU | plain | **legal** |
| H34 | ratio | ANSWER | Home Depot (The) | HD | inverted_the | **legal** |
| H35 | ratio | ANSWER | Merck & Co. | MRK | punctuated | **informal** |
| H36 | ratio | ANSWER | Wynn Resorts | WYNN | multi_word | **legal** |
| | | | Lumentum | LITE | plain | **brand** |
| H37 | ratio | ANSWER | Cooper Companies (The) | COO | inverted_the | **ticker** |
| H38 | ratio | ANSWER_WITH_ASSUMPTION | International Flavors & Fragrances | IFF | punctuated | **informal** |
| H39 | unit_period | ANSWER | Devon Energy | DVN | multi_word | **ticker** |
| H40 | unit_period | ANSWER | Newmont | NEM | plain | **brand** |
| H41 | unit_period | ANSWER_WITH_ASSUMPTION | Travelers Companies (The) | TRV | inverted_the | **brand** |
| H42 | unit_period | ANSWER_WITH_ASSUMPTION | Deere & Company | DE | punctuated | **informal** |
| H43 | unit_period | ANSWER_WITH_ASSUMPTION | Palo Alto Networks | PANW | multi_word | **informal** |
| H44 | unit_period | ABSTAIN | Fortive | FTV | plain | **brand** |
| H45 | ambiguous | ANSWER_WITH_ASSUMPTION | Mosaic Company (The) | MOS | inverted_the | **legal** |
| H46 | ambiguous | ANSWER_WITH_ASSUMPTION | Stanley Black & Decker | SWK | punctuated | **brand** |
| H47 | ambiguous | ANSWER_WITH_ASSUMPTION | NXP Semiconductors | NXPI | multi_word | **legal** |
| H48 | ambiguous | ANSWER_WITH_ASSUMPTION | *(no company)* | | | |
| H49 | ambiguous | ABSTAIN | Cognizant | CTSH | plain | **legal** |
| H50 | ambiguous | ABSTAIN | Mid-America Apartment Communities | MAA | punctuated | **legal** |
| H51 | ambiguous | ABSTAIN | PNC Financial Services | PNC | multi_word | **informal** |
| H52 | out_of_scope | ABSTAIN | Corning Inc. | GLW | plain | **ticker** |
| H53 | out_of_scope | ABSTAIN | F5, Inc. | FFIV | punctuated | **brand** |
| H54 | out_of_scope | ABSTAIN | *(no company)* | | | |
| H55 | out_of_scope | ABSTAIN | *(no company)* | | | |
| H56 | out_of_scope | ABSTAIN | Lilly (Eli) | LLY | multi_word | **brand** |
| H57 | out_of_scope | ABSTAIN | Equifax | EFX | plain | **ticker** |
| H58 | adversarial | ANSWER | O'Reilly Automotive | ORLY | punctuated | **ticker** |
| H59 | adversarial | ANSWER | West Pharmaceutical Services | WST | multi_word | **brand** |
| H60 | adversarial | ABSTAIN | Accenture | ACN | plain | **legal** |
| H61 | adversarial | ABSTAIN | *(no company)* | | | |
| H62 | adversarial | ABSTAIN | *(no company)* | | | |
| H63 | adversarial | ABSTAIN | M&T Bank | MTB | punctuated | **informal** |
| H64 | adversarial | ABSTAIN | General Mills | GIS | multi_word | **informal** |
| H65 | adversarial | ABSTAIN | Cisco | CSCO | plain | **ticker** |
| H66 | schema_bait | ANSWER_WITH_ASSUMPTION | T-Mobile US | TMUS | punctuated | **ticker** |
| H67 | schema_bait | ANSWER_WITH_ASSUMPTION | Align Technology | ALGN | multi_word | **brand** |
| H68 | schema_bait | ABSTAIN | Tapestry, Inc. | TPR | plain | **ticker** |
| H69 | schema_bait | ABSTAIN | Sherwin-Williams | SHW | punctuated | **brand** |
| H70 | schema_bait | ABSTAIN | Broadridge Financial Solutions | BR | multi_word | **brand** |
| H71 | schema_bait | ABSTAIN | Block, Inc. | XYZ | plain | **legal** |
| H72 | grounding | ANSWER | Moody's Corporation | MCO | punctuated | **brand** |
| H73 | grounding | ANSWER | Lockheed Martin | LMT | multi_word | **ticker** |
| H74 | grounding | ANSWER | Centene Corporation | CNC | plain | **legal** |
| | | | McCormick & Company | MKC | punctuated | **informal** |
| H75 | grounding | ANSWER_WITH_ASSUMPTION | Union Pacific Corporation | UNP | multi_word | **ticker** |
| H76 | grounding | ABSTAIN | Cummins | CMI | plain | **legal** |
| H77 | calibration_twin | ANSWER | S&P Global | SPGI | punctuated | **brand** |
| H78 | calibration_twin | ANSWER | WEC Energy Group | WEC | multi_word | **ticker** |
| H79 | calibration_twin | ANSWER | Ecolab | ECL | plain | **legal** |
| H80 | calibration_twin | ANSWER | Lowe's | LOW | punctuated | **brand** |
