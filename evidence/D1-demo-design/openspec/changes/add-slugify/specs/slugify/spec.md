## Purpose

Turning a text into a URL-safe ASCII slug. Written by the product manager from the
proposal's accepted objective (O1) and acceptance criteria (AC1 to AC7).

## ADDED Requirements

### Requirement: Interface

The package SHALL export `slugify` as `aieh_d1_demo.slugify`, a function of one argument
that returns a `str`, and SHALL raise `TypeError` for an argument that is not a `str` (AC1).

#### Scenario: A text gives a str

- **WHEN** `slugify("Hello World")` is called
- **THEN** it returns the `str` `"hello-world"`

#### Scenario: Not a text

- **WHEN** `slugify(b"hello")` or `slugify(None)` is called
- **THEN** it raises `TypeError`

### Requirement: Unicode normalization

The function SHALL normalize the text with Unicode NFKD and remove combining marks, so that
accented Latin letters, compatibility forms and ligatures become ASCII letters and digits;
any character still outside ASCII letters and digits SHALL be treated as a separator (AC2).

#### Scenario: Accents are removed

- **WHEN** `slugify("Crème Brûlée")` is called
- **THEN** it returns `"creme-brulee"`

#### Scenario: Compatibility forms and ligatures are folded

- **WHEN** `slugify("ﬁle")` and `slugify("Ｈｅｌｌｏ")` are called
- **THEN** they return `"file"` and `"hello"`

#### Scenario: Characters without an ASCII form separate words

- **WHEN** `slugify("Straße")` and `slugify("日本語")` are called
- **THEN** they return `"stra-e"` and `""`

### Requirement: Case and digits

The function SHALL lower-case ASCII letters and SHALL keep ASCII digits (AC3).

#### Scenario: Mixed case

- **WHEN** `slugify("Hello World")` is called
- **THEN** it returns `"hello-world"`

#### Scenario: Digits are kept

- **WHEN** `slugify("Version 2.0")` is called
- **THEN** it returns `"version-2-0"`

### Requirement: Separators

The function SHALL replace every maximal run of characters that are not ASCII letters or
digits (whitespace of any kind, punctuation, symbols, underscores and hyphens) with one
hyphen (AC4).

#### Scenario: Whitespace runs

- **WHEN** `slugify("a  b\t\nc")` is called
- **THEN** it returns `"a-b-c"`

#### Scenario: Punctuation, underscores and hyphens

- **WHEN** `slugify("Hello, World!")`, `slugify("foo_bar--baz")` and `slugify("Don't stop")` are called
- **THEN** they return `"hello-world"`, `"foo-bar-baz"` and `"don-t-stop"`

### Requirement: Edges and empty input

The result SHALL NOT start or end with a hyphen, and a text that is empty or has no ASCII
letter or digit after normalization SHALL give the empty string, never an error (AC5).

#### Scenario: Leading and trailing separators

- **WHEN** `slugify("  --Hello--  ")` is called
- **THEN** it returns `"hello"`

#### Scenario: Nothing left

- **WHEN** `slugify("")`, `slugify("   ")` and `slugify("!!!")` are called
- **THEN** each returns `""`

### Requirement: Result form

Every result SHALL be empty or match `^[a-z0-9]+(-[a-z0-9]+)*$`, and `slugify` of a result
SHALL return it unchanged (AC6).

#### Scenario: Idempotent

- **WHEN** `slugify` is applied to the result of any scenario above
- **THEN** it returns that result unchanged

### Requirement: Tests

The package's `unittest` tests SHALL cover every scenario of this specification, use only the
Python standard library and run offline with `python -m unittest discover -s tests` from the
repository root (AC7).

#### Scenario: The suite runs offline

- **WHEN** `python -m unittest discover -s tests` runs from the repository root with no network
- **THEN** every test passes
