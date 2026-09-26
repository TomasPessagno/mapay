import React, { useState } from 'react';
import { IonSearchbar } from '@ionic/react';

interface SearchFieldProps {
  onSearch: (destination: string) => void;
}

const SearchField: React.FC<SearchFieldProps> = ({ onSearch }) => {
  const [query, setQuery] = useState('');

  const handleSearch = (e: React.KeyboardEvent<HTMLIonSearchbarElement>) => {
    if (e.key === 'Enter' && query.trim()) {
      onSearch(query.trim());
    }
  };

  return (
    <IonSearchbar
      value={query}
      onIonInput={(e) => setQuery(e.detail.value!)}
      onKeyPress={handleSearch}
      placeholder="Where to?"
      mode="ios"
      className="ion-no-padding"
      style={{ paddingBottom: '16px' }}
    />
  );
};

export default SearchField;
