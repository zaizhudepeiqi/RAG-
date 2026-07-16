import { render, screen } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import Exception404 from '@/pages/exception/404';

describe('not found page', () => {
  it('renders literal Chinese copy without locale files', () => {
    render(
      <MemoryRouter>
        <Exception404 />
      </MemoryRouter>,
    );

    expect(screen.getByText('抱歉，您访问的页面不存在。')).toBeTruthy();
    expect(
      screen.getByRole('link', { name: '返回首页' }).getAttribute('href'),
    ).toBe('/');
  });
});
