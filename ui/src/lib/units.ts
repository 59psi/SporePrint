export function getTempUnit(): 'f' | 'c' {
  return (localStorage.getItem('sporeprint_temp_unit') as 'f' | 'c') || 'f'
}

export function getWeightUnit(): 'g' | 'oz' {
  return (localStorage.getItem('sporeprint_weight_unit') as 'g' | 'oz') || 'g'
}

export function displayTemp(fahrenheit: number | null | undefined): string {
  if (fahrenheit == null) return '\u2014'
  if (getTempUnit() === 'c') {
    const c = (fahrenheit - 32) * 5 / 9
    return `${c.toFixed(1)}\u00B0C`
  }
  return `${fahrenheit.toFixed(1)}\u00B0F`
}

export function displayWeight(grams: number | null | undefined): string {
  if (grams == null) return '\u2014'
  if (getWeightUnit() === 'oz') {
    const oz = grams / 28.3495
    return `${oz.toFixed(1)} oz`
  }
  return `${grams.toFixed(0)}g`
}

export function tempLabel(): string {
  return getTempUnit() === 'c' ? '\u00B0C' : '\u00B0F'
}

export function weightLabel(): string {
  return getWeightUnit() === 'oz' ? 'oz' : 'g'
}

/** Convert a Fahrenheit value to the user's preferred unit (numeric). */
export function convertTemp(fahrenheit: number): number {
  if (getTempUnit() === 'c') {
    return (fahrenheit - 32) * 5 / 9
  }
  return fahrenheit
}
