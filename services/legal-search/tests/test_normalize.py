from legal_search.normalize import normalize, tokens


def test_hamza_forms_of_alef_fold_together():
    assert normalize('أحكام') == normalize('احكام') == normalize('إحكام')


def test_ta_marbuta_and_alef_maqsura_fold():
    assert normalize('المحكمة') == normalize('المحكمه')
    assert normalize('مستشفى') == normalize('مستشفي')


def test_diacritics_and_tatweel_are_dropped():
    assert normalize('العَقْدُ') == normalize('العقد')
    assert normalize('العـــقد') == normalize('العقد')


def test_clitic_prefixes_reduce_to_the_same_stem():
    assert tokens('العربون والعربون بالعربون عربون') == ['عربون', 'عربون', 'عربون', 'عربون']


def test_short_words_keep_their_letters():
    assert tokens('بيع') == ['بيع']


def test_arabic_indic_digits_become_ascii():
    assert tokens('المادة ١٠٧') == ['ماده', '107']
