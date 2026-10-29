import { BrowserRouter, Route, Routes } from 'react-router-dom'

import AdminApp from './admin/AdminApp'
import ConsoleApp from './console/ConsoleApp'
import DocPage from './pages/DocPage'
import Deploy from './pages/Deploy'
import DocsIndex from './pages/DocsIndex'
import Home from './pages/Home'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/console/*" element={<ConsoleApp />} />
        <Route path="/admin/*" element={<AdminApp />} />
        <Route path="/deploy" element={<Deploy />} />
        <Route path="/docs" element={<DocsIndex />} />
        <Route path="/docs/:slug" element={<DocPage />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App