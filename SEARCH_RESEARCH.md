# Full-Text Search Library Research for Scriptura

## Problem Statement

The current `sword_bridge.search_module` performs a brute-force linear scan through all verses of a selected module, stripping HTML and checking for a substring. While wrapped in an asynchronous thread in `search_panel.py` to prevent UI freezes, the search operation itself can be very slow for large modules, leading to long waiting times for results. The goal is to replace this with an efficient, indexed full-text search solution.

## Chosen Library: Whoosh (with `whoosh-reloaded` considerations)

After evaluating several options, **Whoosh** is selected as the most suitable library for the Scriptura application.

**Why Whoosh?**
*   **Pure Python:** Avoids complex compilation issues with C/Rust extensions, simplifying `pip install` and deployment.
*   **No external database required:** It manages its own index files on disk, avoiding a major architectural change like integrating SQLite FTS5 for database management.
*   **Feature-Rich:** Supports essential full-text search features such as tokenization, stemming, stop words, and configurable scoring, which can be valuable for search quality.
*   **Ease of Use:** Provides a relatively straightforward API for index creation and querying.
*   **Performance:** While not the fastest compared to Rust/C++ based engines, it offers a substantial performance improvement over the current linear scan and is well-suited for a single-user desktop application.
*   **Maintenance:** While the original Whoosh project is less active, the `whoosh-reloaded` fork on GitHub addresses maintenance concerns. For this exercise, we will assume standard `whoosh` is sufficient but note `whoosh-reloaded` as a robust alternative if needed.

## Proposed Integration Plan

The integration will involve changes primarily in `sword_bridge.py` (for index management and actual search execution) and potentially `search_panel.py` (to adapt to Whoosh's search results).

### 1. Installation

The `whoosh` library will need to be installed.
`pip install Whoosh`

### 2. Index Storage

Whoosh stores its index files in a directory. A dedicated directory will be created for each module's index.
*   **Location:** `~/.sword/whoosh_indexes/{module_name}`
*   **Reason:** Centralizes SWORD-related data, allows per-module indexing.

### 3. Schema Definition

A Whoosh schema defines the fields that will be stored and indexed.

```python
from whoosh.fields import Schema, ID, TEXT, NUMERIC
from whoosh.analysis import StemmingAnalyzer # For better search results

bible_schema = Schema(
    module=ID(stored=True),        # Module name (e.g., "KJV") - not searchable, but stored
    book=ID(stored=True),          # Book name (e.g., "Genesis") - stored
    chapter=NUMERIC(stored=True),  # Chapter number - stored
    verse=NUMERIC(stored=True),    # Verse number - stored
    content=TEXT(stored=True, analyzer=StemmingAnalyzer()) # Verse text - searchable, stemmed
)
```
*   `ID`: For fields that are stored but not tokenized (e.g., module, book).
*   `NUMERIC`: For chapter and verse numbers, allowing range queries if needed later.
*   `TEXT`: For the actual verse content, with `StemmingAnalyzer` for better recall (e.g., "runs" will match "run"). `stored=True` means the content can be retrieved directly from the index.

### 4. Index Creation and Update (`sword_bridge.py`)

A new function (e.g., `_build_module_index(module_name)`) will be responsible for creating or updating the Whoosh index for a given module.

*   **Logic:**
    1.  Check if `~/.sword/whoosh_indexes/{module_name}` exists. If not, create it.
    2.  Open the index (or create it if it doesn't exist) using `create_in` or `open_dir`.
    3.  Obtain a `IndexWriter`.
    4.  Iterate through all books and chapters of the `module_name` using the existing `sword_bridge.chapter_count` and `sword_bridge.load_chapter`.
    5.  For each verse:
        *   Extract the raw HTML content from `sword_bridge.load_chapter`.
        *   Strip HTML tags to get plain text (e.g., `re.sub(r'<[^>]+>', '', html)`).
        *   Add the document to the writer: `writer.add_document(module=module_name, book=book, chapter=chapter, verse=v, content=plain_text)`.
    6.  Commit the writer to save the index.
*   **Trigger:** This index building process should be triggered asynchronously:
    *   The first time a user tries to search a module for which no index exists.
    *   Potentially after a new module is installed (this would require changes in `module_manager.py` and `window.py`'s `_on_modules_changed`).
    *   It must run in a separate thread to avoid blocking the UI. A loading indicator will be shown.

### 5. Search Query Execution (`sword_bridge.py`)

Modify the existing `sword_bridge.search_module(module_name, query)` function:

*   **Logic:**
    1.  Ensure the index for `module_name` exists and is up-to-date. If not, trigger `_build_module_index` (and wait for it, or handle asynchronously with user feedback).
    2.  Open the index for the specified `module_name`.
    3.  Create a `QueryParser` for the `content` field.
    4.  Parse the user's `query` string using the `QueryParser`.
    5.  Create a `Searcher` object.
    6.  Execute the search: `results = searcher.search(parsed_query)`.
    7.  Iterate through `results` and extract `book`, `chapter`, `verse`, and `content` (plain text snippet).
    8.  Return the results in a format similar to the current `[(book, chapter, verse, plain_text)]`.

### 6. Adapting SearchPanel (`search_panel.py`)

The `search_panel.py` will need minor adjustments:

*   **`_on_search`:** The current `threading.Thread(target=run, daemon=True).start()` will remain, but the `run` function will now call the Whoosh-integrated `sword_bridge.search_module`.
*   **Results Processing:** The format of results returned by the modified `sword_bridge.search_module` should ideally remain consistent with the current `[(book, ch, v, text)]` to minimize changes in `_populate_results`.

## Considerations for LLM

*   **Atomic Changes:** I will aim to make changes in small, logical steps, describing each `replace` or `write_file` operation clearly.
*   **Dependencies:** I will explicitly call `pip install Whoosh` (or `pip install whoosh-reloaded`) as part of the implementation plan.
*   **Error Handling:** I will add appropriate error handling around Whoosh index operations (e.g., index not found, indexing errors).
*   **User Feedback:** Ensure the user is informed when an index is being built, as this can take some time for large modules.
*   **Persistence:** The index will be stored on disk, so it persists between application sessions.
