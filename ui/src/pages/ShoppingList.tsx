import { useState } from 'react'
import { ShoppingCart, Check, Circle } from 'lucide-react'
import { api } from '../api/client'
import { displayWeight } from '../lib/units'

interface ShoppingItem {
  name: string
  quantity: string
  unit: string
  notes: string | null
  category: string
}

export default function ShoppingList() {
  const [speciesId, setSpeciesId] = useState('')
  const [grows, setGrows] = useState('1')
  const [containerLiters, setContainerLiters] = useState('5')
  const [items, setItems] = useState<ShoppingItem[]>([])
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(false)

  const handleGenerate = async () => {
    if (!speciesId.trim()) return
    setLoading(true)
    setChecked(new Set())
    try {
      const data = await api.get<ShoppingItem[]>(
        `/species/${encodeURIComponent(speciesId.trim())}/shopping-list?grows=${grows}&container_liters=${containerLiters}`
      )
      setItems(data)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  const toggleItem = (index: number) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }

  const categories = items.reduce<Record<string, { item: ShoppingItem; index: number }[]>>((acc, item, i) => {
    if (!acc[item.category]) acc[item.category] = []
    acc[item.category].push({ item, index: i })
    return acc
  }, {})

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Shopping List</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">Generate a supply list for your grow</p>
        </div>
      </div>

      {/* Input controls */}
      <div className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)] mb-6">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Species ID</label>
            <input
              value={speciesId}
              onChange={(e) => setSpeciesId(e.target.value)}
              placeholder="e.g. blue_oyster"
              className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
            />
          </div>
          <div>
            <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Number of Grows</label>
            <input
              type="number"
              min="1"
              value={grows}
              onChange={(e) => setGrows(e.target.value)}
              className="w-24 px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
            />
          </div>
          <div>
            <label className="block text-xs text-[var(--color-text-secondary)] mb-1">Container (L)</label>
            <input
              type="number"
              min="1"
              value={containerLiters}
              onChange={(e) => setContainerLiters(e.target.value)}
              className="w-24 px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-sm focus:outline-none focus:border-[var(--color-accent-gourmet)]"
            />
          </div>
          <button
            onClick={handleGenerate}
            disabled={loading || !speciesId.trim()}
            className="px-4 py-2 rounded-lg bg-[var(--color-accent-gourmet)] text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
          >
            {loading ? 'Generating...' : 'Generate'}
          </button>
        </div>
      </div>

      {/* Shopping list */}
      {Object.keys(categories).length > 0 ? (
        <div className="space-y-4">
          {Object.entries(categories).map(([category, entries]) => (
            <div key={category}>
              <h2 className="text-sm font-medium text-[var(--color-text-secondary)] mb-2 uppercase tracking-wider">
                {category}
              </h2>
              <div className="bg-[var(--color-bg-card)] rounded-xl border border-[var(--color-border)] divide-y divide-[var(--color-border)]">
                {entries.map(({ item, index }) => {
                  const isChecked = checked.has(index)
                  return (
                    <button
                      key={index}
                      onClick={() => toggleItem(index)}
                      className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-[var(--color-bg-hover)] transition-colors"
                    >
                      {isChecked ? (
                        <Check size={16} className="text-green-400 shrink-0" />
                      ) : (
                        <Circle size={16} className="text-[var(--color-text-secondary)] shrink-0" />
                      )}
                      <div className={`flex-1 min-w-0 ${isChecked ? 'line-through opacity-50' : ''}`}>
                        <p className="text-sm font-medium">{item.name}</p>
                        {item.notes && (
                          <p className="text-xs text-[var(--color-text-secondary)]">{item.notes}</p>
                        )}
                      </div>
                      <span className={`text-xs shrink-0 ${isChecked ? 'opacity-50' : 'text-[var(--color-text-secondary)]'}`}>
                        {item.unit === 'g' ? displayWeight(parseFloat(item.quantity)) : `${item.quantity} ${item.unit}`}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}

          <p className="text-xs text-[var(--color-text-secondary)] text-center mt-4">
            {checked.size} of {items.length} items checked
          </p>
        </div>
      ) : items.length === 0 && !loading ? (
        <div className="bg-[var(--color-bg-card)] rounded-xl p-12 border border-[var(--color-border)] text-center">
          <ShoppingCart size={48} className="mx-auto mb-4 text-[var(--color-text-secondary)]" />
          <p className="text-[var(--color-text-secondary)]">Enter a species and parameters to generate your shopping list.</p>
        </div>
      ) : null}
    </div>
  )
}
