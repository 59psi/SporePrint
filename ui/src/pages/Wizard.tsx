import { useState } from 'react'
import { Wand2, ChevronLeft, Star, ArrowRight } from 'lucide-react'
import { api } from '../api/client'

interface WizardResult {
  species_id: string
  common_name: string
  scientific_name: string
  score: number
  reasons: string[]
  tldr: string
}

interface Step {
  key: string
  title: string
  subtitle: string
  options: { value: string; label: string; description: string }[]
}

const steps: Step[] = [
  {
    key: 'level',
    title: 'Experience Level',
    subtitle: 'How familiar are you with mushroom cultivation?',
    options: [
      { value: 'first_time', label: 'First Time', description: 'Never grown mushrooms before' },
      { value: 'some_experience', label: 'Some Experience', description: 'A few grows under my belt' },
      { value: 'advanced', label: 'Advanced', description: 'Experienced grower, agar work, cloning' },
    ],
  },
  {
    key: 'env',
    title: 'Growing Environment',
    subtitle: 'Where will you be growing?',
    options: [
      { value: 'indoor_closet', label: 'Indoor Closet', description: 'Small enclosed space' },
      { value: 'indoor_tent', label: 'Indoor Tent', description: 'Grow tent with controlled climate' },
      { value: 'outdoor_beds', label: 'Outdoor Beds', description: 'Garden beds or outdoor area' },
      { value: 'logs', label: 'Logs', description: 'Inoculated logs, outdoor or shade house' },
    ],
  },
  {
    key: 'temp_range',
    title: 'Temperature Range',
    subtitle: 'What is the typical temperature in your grow space?',
    options: [
      { value: 'cool', label: 'Cool (50-65F)', description: 'Basement, unheated garage' },
      { value: 'moderate', label: 'Moderate (65-75F)', description: 'Room temperature' },
      { value: 'warm', label: 'Warm (75-85F)', description: 'Warm room, summer conditions' },
    ],
  },
  {
    key: 'substrate',
    title: 'Substrate Access',
    subtitle: 'What substrates can you easily obtain?',
    options: [
      { value: 'straw', label: 'Straw', description: 'Wheat or oat straw' },
      { value: 'sawdust', label: 'Sawdust', description: 'Hardwood sawdust or pellets' },
      { value: 'grain', label: 'Grain', description: 'Rye, wheat, or millet' },
      { value: 'manure', label: 'Manure', description: 'Horse or cow manure based' },
      { value: 'all', label: 'All of the above', description: 'Full access to substrates' },
    ],
  },
  {
    key: 'goal',
    title: 'Goal',
    subtitle: 'What is your primary goal?',
    options: [
      { value: 'culinary', label: 'Culinary', description: 'Growing for the kitchen' },
      { value: 'medicinal', label: 'Medicinal', description: 'Health and wellness extracts' },
      { value: 'both', label: 'Both', description: 'Culinary and medicinal' },
      { value: 'research', label: 'Research', description: 'Experimentation and learning' },
    ],
  },
  {
    key: 'commitment',
    title: 'Time Commitment',
    subtitle: 'How much time can you dedicate?',
    options: [
      { value: 'set_and_forget', label: 'Set and Forget', description: 'Minimal daily attention needed' },
      { value: 'daily_attention', label: 'Daily Attention', description: '15-30 minutes per day' },
      { value: 'dedicated_hobbyist', label: 'Dedicated Hobbyist', description: 'Happy to spend an hour or more' },
    ],
  },
]

export default function Wizard() {
  const [currentStep, setCurrentStep] = useState(0)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [results, setResults] = useState<WizardResult[] | null>(null)
  const [loading, setLoading] = useState(false)

  const handleSelect = async (value: string) => {
    const step = steps[currentStep]
    const newAnswers = { ...answers, [step.key]: value }
    setAnswers(newAnswers)

    if (currentStep < steps.length - 1) {
      setCurrentStep(currentStep + 1)
    } else {
      setLoading(true)
      try {
        const params = new URLSearchParams(newAnswers)
        const data = await api.get<WizardResult[]>(`/species/recommend?${params}`)
        setResults(data)
      } catch {
        // ignore
      } finally {
        setLoading(false)
      }
    }
  }

  const handleBack = () => {
    if (results) {
      setResults(null)
    } else if (currentStep > 0) {
      setCurrentStep(currentStep - 1)
    }
  }

  const handleReset = () => {
    setCurrentStep(0)
    setAnswers({})
    setResults(null)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="text-center">
          <Wand2 size={48} className="mx-auto mb-4 text-[var(--color-accent-gourmet)] animate-pulse" />
          <p className="text-[var(--color-text-secondary)]">Finding the best species for you...</p>
        </div>
      </div>
    )
  }

  if (results) {
    return (
      <div>
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-semibold">Your Recommendations</h1>
            <p className="text-sm text-[var(--color-text-secondary)]">Top species matched to your profile</p>
          </div>
          <button
            onClick={handleReset}
            className="px-4 py-2 rounded-lg bg-[var(--color-bg-card)] border border-[var(--color-border)] text-sm hover:border-[var(--color-bg-hover)] transition-colors"
          >
            Start Over
          </button>
        </div>

        <div className="space-y-3">
          {results.map((r, i) => (
            <div
              key={r.species_id}
              className="bg-[var(--color-bg-card)] rounded-xl p-5 border border-[var(--color-border)]"
            >
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-3">
                  <span className="text-lg font-bold text-[var(--color-text-secondary)]">#{i + 1}</span>
                  <div>
                    <h3 className="font-medium">{r.common_name}</h3>
                    <p className="text-sm text-[var(--color-text-secondary)] italic">{r.scientific_name}</p>
                  </div>
                </div>
                <div className="flex items-center gap-1 text-amber-400">
                  <Star size={16} fill="currentColor" />
                  <span className="text-sm font-semibold">{r.score}</span>
                </div>
              </div>
              <p className="text-sm text-[var(--color-text-secondary)] mb-3">{r.tldr}</p>
              <div className="flex flex-wrap gap-1.5">
                {r.reasons.map((reason, j) => (
                  <span
                    key={j}
                    className="px-2 py-0.5 rounded-full text-xs bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)]"
                  >
                    {reason}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const step = steps[currentStep]
  const progress = ((currentStep + 1) / steps.length) * 100

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">Species Wizard</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">Answer a few questions to find your ideal species</p>
        </div>
      </div>

      {/* Progress bar */}
      <div className="mb-8">
        <div className="flex items-center justify-between text-xs text-[var(--color-text-secondary)] mb-2">
          <span>Step {currentStep + 1} of {steps.length}</span>
          <span>{Math.round(progress)}%</span>
        </div>
        <div className="h-1.5 bg-[var(--color-bg-card)] rounded-full overflow-hidden">
          <div
            className="h-full bg-[var(--color-accent-gourmet)] rounded-full transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Step content */}
      <div className="mb-6">
        {currentStep > 0 && (
          <button
            onClick={handleBack}
            className="flex items-center gap-1 text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] mb-4"
          >
            <ChevronLeft size={14} />
            Back
          </button>
        )}
        <h2 className="text-xl font-medium mb-1">{step.title}</h2>
        <p className="text-sm text-[var(--color-text-secondary)] mb-4">{step.subtitle}</p>
      </div>

      {/* Options */}
      <div className="space-y-2">
        {step.options.map((opt) => (
          <button
            key={opt.value}
            onClick={() => handleSelect(opt.value)}
            className={`w-full flex items-center justify-between p-4 rounded-xl border transition-colors text-left ${
              answers[step.key] === opt.value
                ? 'bg-[var(--color-accent-gourmet)]/10 border-[var(--color-accent-gourmet)]'
                : 'bg-[var(--color-bg-card)] border-[var(--color-border)] hover:border-[var(--color-bg-hover)]'
            }`}
          >
            <div>
              <p className="font-medium text-sm">{opt.label}</p>
              <p className="text-xs text-[var(--color-text-secondary)]">{opt.description}</p>
            </div>
            <ArrowRight size={16} className="text-[var(--color-text-secondary)]" />
          </button>
        ))}
      </div>
    </div>
  )
}
