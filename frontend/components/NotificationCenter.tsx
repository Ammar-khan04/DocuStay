
import React, { useState } from 'react';
import { Card } from './UI';

export interface Notification {
  id: string;
  type: 'guest' | 'warning' | 'alert' | 'success';
  title: string;
  message: string;
  time: string;
  read: boolean;
}

export const NotificationCenter: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const unreadCount = notifications.filter(n => !n.read).length;

  const markAllRead = () => {
    setNotifications(notifications.map(n => ({ ...n, read: true })));
  };

  return (
    <div className="relative">
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="relative p-2 text-gray-400 hover:text-white transition-colors focus:outline-none"
      >
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"></path></svg>
        {unreadCount > 0 && (
          <span className="absolute top-1.5 right-1.5 w-4 h-4 bg-blue-600 text-white text-[10px] font-black flex items-center justify-center rounded-full border-2 border-[#0a0a0f] shadow-lg">
            {unreadCount}
          </span>
        )}
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)}></div>
          <div className="absolute right-0 mt-4 w-96 z-50 animate-in fade-in slide-in-from-top-2 duration-200">
            <Card className="shadow-[0_20px_50px_rgba(0,0,0,0.5)] border-gray-800">
              <div className="p-4 border-b border-gray-800 flex justify-between items-center bg-white/5">
                <h3 className="font-bold text-white">Notifications</h3>
                <button onClick={markAllRead} className="text-xs text-blue-400 hover:text-blue-300 font-bold">Mark all as read</button>
              </div>
              <div className="max-h-[400px] overflow-y-auto no-scrollbar">
                {notifications.length === 0 ? (
                  <div className="p-8 text-center text-gray-500 text-sm italic">All caught up!</div>
                ) : (
                  notifications.map(n => (
                    <div key={n.id} className={`p-4 border-b border-gray-800/50 hover:bg-white/5 transition-colors group relative ${!n.read ? 'bg-blue-600/5' : ''}`}>
                      <div className="flex gap-4">
                        <div className={`mt-1 w-2 h-2 rounded-full flex-shrink-0 ${n.read ? 'bg-gray-700' : 'bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)]'}`}></div>
                        <div>
                          <p className="text-sm font-bold text-white mb-1">{n.title}</p>
                          <p className="text-xs text-gray-400 leading-relaxed mb-2">{n.message}</p>
                          <p className="text-[10px] font-bold text-gray-600 uppercase tracking-tighter">{n.time}</p>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
              <div className="p-3 text-center border-t border-gray-800">
                <button className="text-xs text-gray-500 hover:text-white font-bold uppercase tracking-widest">View All Activity</button>
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  );
};
