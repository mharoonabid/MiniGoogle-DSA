import { useState, useEffect, useCallback, useRef } from 'react'
import './App.css'

const API_BASE = 'http://localhost:5000'

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

  // Debounced autocomplete
  useEffect(() => {
    if (query.length < 2) {
      setSuggestions([])
      setShowSuggestions(false)
      return
    }

    const timer = setTimeout(async () => {
      try {
        const res = await fetch(`${API_BASE}/autocomplete?prefix=${encodeURIComponent(query)}`)
        if (res.ok) {
          const data = await res.json()
          setSuggestions(data.suggestions || [])
          setShowSuggestions(true)
        }
      } catch (err) {
        console.error('Autocomplete error:', err)
      }
    }, 150)

    return () => clearTimeout(timer)
  }, [query])

  const handleSearch = useCallback(async (searchQuery) => {
    const q = searchQuery || query
    if (!q.trim()) return

    setLoading(true)
    setError(null)
    setShowSuggestions(false)
    setSuggestions([])

    try {
      const url = `${API_BASE}/search?q=${encodeURIComponent(q)}&mode=${mode}&semantic=${semantic}`
      const res = await fetch(url)

      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || 'Search failed')
      }

      const data = await res.json()
      setResults(data)
      setSearchTime(data.search_time_ms)
    } catch (err) {
      setError(err.message)
      setResults(null)
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
          handleSearch(selected.word)
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
              onFocus={() => query.length >= 2 && suggestions.length > 0 && setShowSuggestions(true)}
            />
            <button
              className="search-button"
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
          </div>
        </div>

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
                    <div className="result-doc-id">
                      <a
                        href={`https://www.ncbi.nlm.nih.gov/pmc/articles/${result.doc_id}/`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {result.doc_id}
                      </a>
                    </div>
                    <div className="result-scores">
                      <span className="score">Score: {result.score?.toFixed(4)}</span>
                      {result.tfidf_score !== undefined && (
                        <span className="score">TF-IDF: {result.tfidf_score?.toFixed(4)}</span>
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
