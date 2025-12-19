import { useState, useEffect, useCallback, useRef } from 'react'
import './App.css'

const API_BASE = '/api'


function App() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState(null)
  const [suggestions, setSuggestions] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [mode, setMode] = useState('and')
  const [semantic, setSemantic] = useState(true)
  const [searchTime, setSearchTime] = useState(null)
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const searchInputRef = useRef(null)
  const suggestionsRef = useRef(null)

  // Document upload state
  const [showUpload, setShowUpload] = useState(false)
  const [uploadLoading, setUploadLoading] = useState(false)
  const [uploadResult, setUploadResult] = useState(null)
  const [uploadError, setUploadError] = useState(null)
  const fileInputRef = useRef(null)

  // Cache for autocomplete results
  const autocompleteCache = useRef(new Map())
  const abortControllerRef = useRef(null)
  const searchAbortRef = useRef(null)  // Abort controller for search requests

  // Optimized autocomplete with minimal delay and aggressive caching
  useEffect(() => {
    if (query.length < 1) {
      setSuggestions([])
      setShowSuggestions(false)
      return
    }

    // Check cache first - instant response
    const cacheKey = query.toLowerCase()
    if (autocompleteCache.current.has(cacheKey)) {
      setSuggestions(autocompleteCache.current.get(cacheKey))
      setShowSuggestions(true)
      return
    }

    // Minimal debounce (50ms) for near-instant feel
    const timer = setTimeout(async () => {
      // Cancel any in-flight request immediately
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
      abortControllerRef.current = new AbortController()

      try {
        const res = await fetch(
          `${API_BASE}/autocomplete?prefix=${encodeURIComponent(query)}`,
          {
            signal: abortControllerRef.current.signal,
            // Use keepalive for faster connection reuse
            keepalive: true
          }
        )
        if (res.ok) {
          const data = await res.json()
          const suggestions = data.suggestions || []
          // LRU cache with 200 entries for better hit rate
          if (autocompleteCache.current.size > 200) {
            const firstKey = autocompleteCache.current.keys().next().value
            autocompleteCache.current.delete(firstKey)
          }
          autocompleteCache.current.set(cacheKey, suggestions)
          setSuggestions(suggestions)
          setShowSuggestions(true)
        }
      } catch (err) {
        if (err.name !== 'AbortError') {
          console.error('Autocomplete error:', err)
        }
      }
    }, 50)

    return () => {
      clearTimeout(timer)
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [query])

  const handleSearch = useCallback(async (searchQuery) => {
    const q = searchQuery || query
    if (!q.trim()) return

    // Cancel any pending search request immediately
    if (searchAbortRef.current) {
      searchAbortRef.current.abort()
    }
    searchAbortRef.current = new AbortController()

    // Update UI state immediately (batch these updates)
    setShowSuggestions(false)
    setLoading(true)
    setError(null)

    try {
      const url = `${API_BASE}/search?q=${encodeURIComponent(q)}&mode=${mode}&semantic=${semantic}`
      const res = await fetch(url, {
        signal: searchAbortRef.current.signal,
        headers: {
          'Accept': 'application/json',
        }
      })

      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Search failed')
      }

      const data = await res.json()
      setResults(data)
      setSearchTime(data.search_time_ms)
    } catch (err) {
      // Don't show error for aborted requests
      if (err.name !== 'AbortError') {
        setError(err.message)
        setResults(null)
      }
    } finally {
      setLoading(false)
    }
  }, [query, mode, semantic])

  const handleKeyDown = (e) => {
    if (!showSuggestions || suggestions.length === 0) {
      if (e.key === 'Enter') {
        handleSearch()
      }
      return
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setSelectedIndex(prev => Math.min(prev + 1, suggestions.length - 1))
        break
      case 'ArrowUp':
        e.preventDefault()
        setSelectedIndex(prev => Math.max(prev - 1, -1))
        break
      case 'Enter':
        e.preventDefault()
        if (selectedIndex >= 0) {
          const selected = suggestions[selectedIndex]
          setQuery(selected.word)
          setShowSuggestions(false)
          // Only auto-search for single words, let user confirm multi-word
          if (!selected.word.includes(' ')) {
            handleSearch(selected.word)
          }
        } else {
          handleSearch()
        }
        break
      case 'Escape':
        setShowSuggestions(false)
        setSelectedIndex(-1)
        break
    }
  }

  const handleSuggestionClick = (word) => {
    setQuery(word)
    setShowSuggestions(false)
    handleSearch(word)
  }

  // Handle document upload
  const handleFileUpload = useCallback(async (e) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploadLoading(true)
    setUploadError(null)
    setUploadResult(null)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch(`${API_BASE}/upload`, {
        method: 'POST',
        body: formData
      })

      const data = await res.json()

      if (res.ok && data.success) {
        setUploadResult(data)
        // Clear the file input
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
      } else {
        setUploadError(data.error || data.detail || 'Upload failed')
      }
    } catch (err) {
      setUploadError(err.message || 'Upload failed')
    } finally {
      setUploadLoading(false)
    }
  }, [])

  // Close suggestions on outside click
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (suggestionsRef.current && !suggestionsRef.current.contains(e.target) &&
          searchInputRef.current && !searchInputRef.current.contains(e.target)) {
        setShowSuggestions(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div className="app">
      <header className="header">
        <h1 className="title">MiniGoogle</h1>
        <p className="subtitle">Search the CORD-19 Research Dataset</p>
      </header>

      <main className="main">
        <div className="search-container">
          <div className="search-box">
            <input
              ref={searchInputRef}
              type="text"
              className="search-input"
              placeholder="Search for research papers..."
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setSelectedIndex(-1)
              }}
              onKeyDown={handleKeyDown}
              onFocus={() => query.length >= 1 && suggestions.length > 0 && setShowSuggestions(true)}
            />
            <button
              className={`search-button ${loading ? 'loading' : ''}`}
              onClick={() => handleSearch()}
              disabled={loading}
            >
              {loading ? 'Searching...' : 'Search'}
            </button>
          </div>

          {showSuggestions && suggestions.length > 0 && (
            <ul className="suggestions" ref={suggestionsRef}>
              {suggestions.map((s, i) => (
                <li
                  key={s.word}
                  className={`suggestion-item ${i === selectedIndex ? 'selected' : ''}`}
                  onClick={() => handleSuggestionClick(s.word)}
                  onMouseEnter={() => setSelectedIndex(i)}
                >
                  <span className="suggestion-word">{s.word}</span>
                  <span className="suggestion-df">{s.df.toLocaleString()} docs</span>
                </li>
              ))}
            </ul>
          )}

          <div className="options">
            <div className="option-group">
              <label className="option-label">Mode:</label>
              <select value={mode} onChange={(e) => setMode(e.target.value)} className="option-select">
                <option value="and">AND (all words)</option>
                <option value="or">OR (any word)</option>
              </select>
            </div>
            <div className="option-group">
              <label className="option-label">
                <input
                  type="checkbox"
                  checked={semantic}
                  onChange={(e) => setSemantic(e.target.checked)}
                />
                Semantic Search
              </label>
            </div>
            <div className="option-group">
              <button
                className="upload-toggle-btn"
                onClick={() => setShowUpload(!showUpload)}
              >
                {showUpload ? 'Hide Upload' : 'Add Document'}
              </button>
            </div>
          </div>
        </div>

        {/* Document Upload Section */}
        {showUpload && (
          <div className="upload-section">
            <h3 className="upload-title">Add New Document</h3>
            <p className="upload-desc">Upload a document to index it instantly. Supports .txt, .json, .md files.</p>

            <div className="upload-box">
              <input
                ref={fileInputRef}
                type="file"
                accept=".txt,.json,.md,.text"
                onChange={handleFileUpload}
                disabled={uploadLoading}
                className="file-input"
                id="file-upload"
              />
              <label htmlFor="file-upload" className="file-label">
                {uploadLoading ? 'Indexing...' : 'Choose File or Drag & Drop'}
              </label>
            </div>

            {uploadError && (
              <div className="upload-error">
                <strong>Error:</strong> {uploadError}
              </div>
            )}

            {uploadResult && (
              <div className="upload-success">
                <strong>Document indexed successfully!</strong>
                <ul className="upload-stats">
                  <li>Document ID: <code>{uploadResult.doc_id}</code></li>
                  <li>Title: {uploadResult.title || 'Untitled'}</li>
                  <li>Terms indexed: {uploadResult.total_terms?.toLocaleString()}</li>
                  <li>Unique terms: {uploadResult.unique_terms?.toLocaleString()}</li>
                  {uploadResult.new_terms_added > 0 && (
                    <li>New terms added: {uploadResult.new_terms_added}</li>
                  )}
                  <li>Indexing time: {uploadResult.indexing_time_ms}ms</li>
                </ul>
                <button
                  className="search-indexed-btn"
                  onClick={() => {
                    setQuery(uploadResult.doc_id)
                    setShowUpload(false)
                    handleSearch(uploadResult.doc_id)
                  }}
                >
                  Search for this document
                </button>
              </div>
            )}
          </div>
        )}

        {error && (
          <div className="error">
            <strong>Error:</strong> {error}
          </div>
        )}

        {results && (
          <div className="results-container">
            <div className="results-header">
              <span className="results-count">
                Found <strong>{results.result_count?.toLocaleString() || 0}</strong> documents
              </span>
              {searchTime && (
                <span className="results-time">({searchTime}ms)</span>
              )}
            </div>

            {results.expanded_terms && results.expanded_terms.length > 0 && (
              <div className="expanded-terms">
                <span className="expanded-label">Query expansion:</span>
                {results.expanded_terms.map((term, i) => (
                  <span key={i} className={`term ${term.weight < 1 ? 'expanded' : 'original'}`}>
                    {term.word}
                    {term.weight < 1 && <sup>{term.weight.toFixed(2)}</sup>}
                  </span>
                ))}
              </div>
            )}

            <ul className="results-list">
              {results.results?.map((result, i) => (
                <li key={result.doc_id} className="result-item">
                  <div className="result-rank">{result.rank || i + 1}</div>
                  <div className="result-content">
                    {/* Title as main heading */}
                    <h3 className="result-title">
                      <a
                        href={`https://www.ncbi.nlm.nih.gov/pmc/articles/${result.doc_id}/`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {result.title || result.doc_id}
                      </a>
                    </h3>

                    {/* Authors */}
                    {result.authors && result.authors.length > 0 && (
                      <div className="result-authors">
                        {result.authors.join(', ')}
                      </div>
                    )}

                    {/* Abstract snippet */}
                    {result.abstract && (
                      <p className="result-abstract">{result.abstract}</p>
                    )}

                    {/* Doc ID (smaller, secondary) */}
                    <div className="result-doc-id">
                      Document ID: {result.doc_id}
                    </div>

                    {/* Scores */}
                    <div className="result-scores">
                      <span className="score">Score: {result.score?.toFixed(4)}</span>
                      {result.tfidf_score !== undefined && (
                        <span className="score">BM25: {result.tfidf_score?.toFixed(4)}</span>
                      )}
                      {result.pagerank_score !== undefined && (
                        <span className="score">PageRank: {result.pagerank_score?.toFixed(4)}</span>
                      )}
                      {result.matched_terms !== undefined && (
                        <span className="score">
                          Matched: {result.matched_terms}/{result.total_terms}
                        </span>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>

            {results.results?.length === 0 && (
              <div className="no-results">
                No documents found matching your query.
              </div>
            )}
          </div>
        )}
      </main>

      <footer className="footer">
        <p>MiniGoogle - CORD-19 Search Engine | DSA Project</p>
      </footer>
    </div>
  )
}

export default App
