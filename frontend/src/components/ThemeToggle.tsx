import { Moon, Sun } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';

interface ThemeToggleProps {
  className?: string;
  variant?: 'compact' | 'pill' | 'minimal';
  showLabel?: boolean;
}

export default function ThemeToggle({
  className = '',
  variant = 'compact',
  showLabel = false,
}: ThemeToggleProps) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';

  if (variant === 'pill') {
    return (
      <button
        type="button"
        onClick={toggleTheme}
        className={`theme-toggle-pill ${className}`}
        aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
        title={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
      >
        <span className={`theme-toggle-indicator ${isDark ? 'dark' : 'light'}`}>
          {isDark ? <Moon size={13} /> : <Sun size={13} />}
        </span>
        <span className="theme-toggle-label">{isDark ? 'Dark' : 'Light'}</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className={`theme-toggle-btn ${variant} ${className}`}
      aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
      title={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
    >
      <div className="theme-toggle-icon-wrap">
        {isDark ? (
          <Sun size={17} className="theme-icon sun" />
        ) : (
          <Moon size={17} className="theme-icon moon" />
        )}
      </div>
      {showLabel && (
        <span className="theme-toggle-text">
          {isDark ? 'Light' : 'Dark'}
        </span>
      )}
    </button>
  );
}
