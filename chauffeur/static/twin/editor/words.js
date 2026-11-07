export function sentence(text, fallback = '') {
  const words = String(text || fallback).trim().replace(/[.!?]+$/, '');
  return words ? words[0].toUpperCase() + words.slice(1) + '.' : '';
}

export function confidenceWords(value) {
  return Number(value) >= .8 ? 'I am sure' : Number(value) >= .5 ? 'I am fairly sure' : 'I am unsure';
}

export function pauseWords(pause) {
  return `${sentence(pause.why, 'This is the outline I read from your drawing')} ${sentence(confidenceWords(pause.confidence))}`;
}

export function sheetMaster(sheets, source, page) {
  return sheets.pages?.find(p => p.source === source && p.page === page)?.master_size
    || sheets.registrations?.find(p => p.source === source && p.page === page)?.master_size
    || sheets.page_roles?.find(p => p.source === source && p.page === page)?.master_size || null;
}
